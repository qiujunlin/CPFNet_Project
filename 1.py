def train_eval(predict, target,classes):    # pred_seg=torch.argmax(torch.exp(predict),dim=1).int()
    pred_seg = predict.data.cpu().numpy()  # n h w int64 ndarray
    label_seg = target.data.cpu().numpy().astype(dtype=np.int)  # n h w float32  -> int32 ndarray
    assert (pred_seg.shape == label_seg.shape)
    acc = (pred_seg == label_seg).sum() / (
                pred_seg.shape[0] * pred_seg.shape[1] * pred_seg.shape[2])  # acc ����������ͬ������ֵռ�����صĴ�С
    overlap = ((pred_seg == classes) * (label_seg == classes)).sum()
    union = (pred_seg == classes).sum() + (label_seg == classes).sum()
    dice = (2 * overlap + 0.1) / (union + 0.1)
    return dice, acc
def val(args, model, dataloader):
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
            predicts= model(data)  # Ԥ����  ����sigmod��� float32
            predict = (predict>0.5).float()  # int64 # n h w ��ȡ���ǽ�� Ԥ��Ľ����������һ���
            batch_size = predict.size()[0]  # ��ǰ��������С   1
            counter += batch_size  # ÿ�μ�һ
            cur_cube.append(predict)  # (1,h,w)
            cur_label_cube.append(label)  #

        predict_cube = torch.stack(cur_cube, dim=0).squeeze()  # (n,h,w) int 64 tensor
        label_cube = torch.stack(cur_label_cube, dim=0).squeeze()  # n hw float32 tensor
        # ����
        Dice,acc = train_eval(predict_cube, label_cube, args.num_classes)
        print('Dice1:', Dice)
        print('Acc:', acc)
        return Dice, acc