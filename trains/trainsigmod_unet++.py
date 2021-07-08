# coding=gbk
from torch.utils.data import DataLoader

import socket
from datetime import datetime
import os
import torch
from tensorboardX import SummaryWriter
import tqdm
import torch.nn as nn
from torch.nn import functional as F
import numpy as np
from PIL import Image
import utils.utils as u
import utils.loss as LS
from config.config import DefaultConfig
import torch.backends.cudnn as cudnn
from torch.optim import lr_scheduler

"""
����ģ�� ���ݼ���
"""
from dataset.Dataset import OCT
from model.BaseNet import CPFNet
from model.unet import UNet
from model.unetplus import  NestedUNet
from  utils import  utils as u

def valunetplus(args, model, dataloader):
    print('\n')
    print('Start Validation!')
    with torch.no_grad():  # �����۹�����ֹͣ���ݶ�  �ӿ��ٶȵ�����
        model.eval()  # !!!���ۺ�������ʹ��
        tbar = tqdm.tqdm(dataloader, desc='\r')
        cur_cube=[]
        cur_label_cube=[]
        counter=0
        for i, (data, labels) in enumerate(tbar):
            # tbar.update()
            if torch.cuda.is_available() and args.use_gpu:
                data = data.cuda()
                label = labels[0].cuda()
            slice_num = labels[1].long().item()  # ��ȡ�ܹ���label����  86
            # get RGB predict image
            predict = model(data)  # Ԥ����  ����sigmod��� float32
            predict = (predict[-1]>0.5).float()  # int64 # n h w ��ȡ���ǽ�� Ԥ��Ľ����������һ���
            batch_size = predict.size()[0]  # ��ǰ��������С   1
            counter += batch_size  # ÿ�μ�һ
            cur_cube.append(predict)  # (1,h,w)
            cur_label_cube.append(label)  #
        predict_cube = torch.stack(cur_cube, dim=0).squeeze()  # (n,h,w) int 64 tensor
        label_cube = torch.stack(cur_label_cube, dim=0).squeeze()  # n hw float32 tensor
        # ����
        Dice,acc = u.train_eval(predict_cube, label_cube, args.num_classes)
        print('Dice1:', Dice)
        print('Acc:', acc)
        return Dice, acc

def train(args, model, optimizer, criterion, scheduler, dataloader_train, dataloader_val):
    # comments=os.getcwd().split('/')[-1]
    current_time = datetime.now().strftime('%b%d_%H-%M-%S')
    log_dir = os.path.join(args.log_dirs, current_time + '_' + socket.gethostname())
    writer = SummaryWriter(log_dir=log_dir)
    step = 0
    best_pred = 0.0
    for epoch in range(args.num_epochs):
        # ��̬����ѧϰ��,ʹ�ùٷ���ѧϰ�ʵ�����ʹ���Լ���
        if (args.scheduler == None):
            lr = optimizer.state_dict()['param_groups'][0]['lr']
        else:
            lr = u.adjust_learning_rate(args, optimizer, epoch)
        model.train()
        tq = tqdm.tqdm(total=len(dataloader_train) * args.batch_size)
        tq.set_description('epoch %d, lr %f' % (epoch, lr))
        loss_record = []
        train_loss = 0.0

        for i, (data, label) in enumerate(dataloader_train):
            # if i>9:
            #     break
            if torch.cuda.is_available() and args.use_gpu:
                data = data.cuda()
                label = label.cuda().float()
            """
            ����ѵ�� ��׼����
            """
            optimizer.zero_grad()
            main_out = model(data)

            """
            ������ʧ����,����Ϊdepp-suprervision ����Ҫ���ĸ�������мල
            """

            loss_aux =0
            loss_main =0

            for i , data in enumerate(main_out):
               loss_aux += criterion[0](data, label)
               loss_main += criterion[1](data,label)
            loss = (loss_main + loss_aux)/len(main_out)
            loss.backward()
            optimizer.step()

            tq.update(args.batch_size)
            train_loss += loss.item()
            tq.set_postfix(loss='%.6f' % (train_loss / (i + 1)))  # ��ʾ��������Ϣ
            step += 1
            if step % 10 == 0:
                writer.add_scalar('Train/loss_step', loss, step)
            loss_record.append(loss.item())
        tq.close()
        loss_train_mean = np.mean(loss_record)
        writer.add_scalar('Train/loss_epoch', float(loss_train_mean), epoch)
        print('loss for train : %f' % (loss_train_mean))

        if epoch % args.validation_step == 0:
            Dice1, acc = u.val_sigmod(args, model, dataloader_val)
            """
            ����ѧϰ��
            """
            if args.scheduler == 'CosineAnnealingLR':
                scheduler.step()
            elif args.scheduler == 'ReduceLROnPlateau':
                scheduler.step(Dice1)

            writer.add_scalar('Valid/Dice1_val', Dice1, epoch)
            writer.add_scalar('Valid/Acc_val', acc, epoch)

            """
            ������õ�dice,�����ǰֵ��֮ǰ�Ĵ� �ͱ��� ���������
            """

            is_best = Dice1 > best_pred
            best_pred = max(best_pred, Dice1)
            checkpoint_dir = args.save_model_path
            # checkpoint_dir=os.path.join(checkpoint_dir_root,str(k_fold))
            if not os.path.exists(checkpoint_dir):
                os.makedirs(checkpoint_dir)
            checkpoint_latest = os.path.join(checkpoint_dir, 'checkpoint_latest.pth.tar')
            u.save_checkpoint({
                'epoch': epoch + 1,
                'state_dict': model.state_dict(),
                'best_dice': best_pred,
            }, best_pred, epoch, is_best, args.net_work, checkpoint_dir, filename=checkpoint_latest)


def test(model, dataloader, args):
    print('start test!')
    with torch.no_grad():
        model.eval()
        # precision_record = []
        tq = tqdm.tqdm(dataloader, desc='\r')
        tq.set_description('test')
        comments = os.getcwd().split('/')[-1]
        for i, (data, label_path) in enumerate(tq):
            if torch.cuda.is_available() and args.use_gpu:
                data = data.cuda()
                # label = label.cuda()
            aux_pred, predict = model(data)
            predict = (predict[-1]>0.5).float()

            pred = predict.data.cpu().numpy()
            sum1 = (pred == 1).sum()
            pred_RGB = OCT.COLOR_DICT[pred.astype(np.uint8)]
            sum2 = (pred_RGB[0, :, :, 0] == 255).sum()
            for index, item in enumerate(label_path):
                save_img_path = label_path[index].replace('mask', 'predict')
                if not os.path.exists(os.path.dirname(save_img_path)):
                    os.makedirs(os.path.dirname(save_img_path))
                img = Image.fromarray(pred_RGB[index].squeeze().astype(np.uint8))
                img.save(save_img_path)
                tq.set_postfix(str=str(save_img_path))
        tq.close()


def main(mode='train', args=None):
    """
    create dataset and dataloader
    """
    dataset_path = os.path.join(args.data, args.dataset)
    dataset_train = OCT(dataset_path, scale=(args.crop_height, args.crop_width), mode='train')
    dataloader_train = DataLoader(
        dataset_train,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=True,
        drop_last=True
    )

    dataset_val = OCT(dataset_path, scale=(args.crop_height, args.crop_width), mode='val')
    dataloader_val = DataLoader(
        dataset_val,
        # this has to be 1
        batch_size=len(args.cuda.split(',')),
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=True,
        drop_last=True
    )

    dataset_test = OCT(dataset_path, scale=(args.crop_height, args.crop_width), mode='test')
    dataloader_test = DataLoader(
        dataset_test,
        # this has to be 1
        batch_size=len(args.cuda.split(',')),
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=True,
        drop_last=False
    )

    # build model
    os.environ['CUDA_VISIBLE_DEVICES'] = args.cuda

    """
    load model
    """

    model_all = {'BaseNet': CPFNet(out_planes=args.num_classes),
                 'UNet': UNet(),
                 'NestedUNet':NestedUNet(num_classes=1,deep_supervision=True)}
    model = model_all[args.net_work]
    print(args.net_work)
    cudnn.benchmark = True
    # model._initialize_weights()
    if torch.cuda.is_available() and args.use_gpu:
        model = torch.nn.DataParallel(model).cuda()
    # load pretrained model if exists
    if args.pretrained_model_path and mode == 'test':
        print("=> loading pretrained model '{}'".format(args.pretrained_model_path))
        checkpoint = torch.load(args.pretrained_model_path)
        model.load_state_dict(checkpoint['state_dict'])
        print('Done!')

    """
     optimizer and  scheduler 
    """
    optimizer = torch.optim.SGD(model.parameters(), lr=args.lr, momentum=args.momentum, weight_decay=args.weight_decay)

    if args.scheduler == 'CosineAnnealingLR':
        scheduler = lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=args.num_epochs, eta_min=args.min_lr)
    elif args.scheduler == 'ReduceLROnPlateau':
        scheduler = lr_scheduler.ReduceLROnPlateau(optimizer, factor=args.factor, patience=args.patience,
                                                   verbose=1, min_lr=args.min_lr)
    elif args.scheduler == 'MultiStepLR':
        scheduler = lr_scheduler.MultiStepLR(optimizer, milestones=[int(e) for e in args.milestones.split(',')],
                                             gamma=args.gamma)
    elif args.scheduler == 'ConstantLR':
        scheduler = None
    elif args.scheduler == "StepLR":
        scheduler = lr_scheduler.StepLR(optimizer, step_size=30)
    else:
        scheduler =None

    """
     loss
    """
    criterion_aux = nn.BCELoss(weight=None)
    criterion_main = LS.Multi_DiceLoss(class_num=1)
    criterion = [criterion_aux, criterion_main]

    if mode == 'train':
        train(args, model, optimizer, criterion, scheduler, dataloader_train, dataloader_val)
    if mode == 'test':
        test(model, dataloader_test, args)


if __name__ == '__main__':
    seed = 1234
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    args = DefaultConfig()

    modes = args.mode

    if modes == 'train':
        main(mode='train', args=args)
    elif modes == 'test':
        main(mode='test', args=args)

