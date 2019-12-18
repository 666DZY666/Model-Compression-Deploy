#coding=utf-8
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
import math
import argparse
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.autograd import Variable
import torchvision
import torchvision.transforms as transforms
import util_w_t_b
#import util_w_t_gap
from models import nin_gc
#from models import nin
#from models import nin_bn_conv

# 随机种子——训练结果可复现
def setup_seed(seed):
    # 为CPU设置种子用于生成随机数,以使得结果是确定的
    torch.manual_seed(seed)                    
    #torch.cuda.manual_seed(seed)
    # 为GPU设置种子用于生成随机数,以使得结果是确定的
    torch.cuda.manual_seed_all(seed)           
    # 为numpy设置种子用于生成随机数,以使得结果是确定的
    np.random.seed(seed)
    # 将会让程序在开始时花费一点额外时间，为整个网络的每个卷积层
    # 搜索最适合它的卷积实现算法，进而实现网络的加速。适用场景是
    # 网络结构固定（不是动态变化的），网络的输入形状（包括 batch size，
    # 图片大小，输入的通道）是不变的，其实也就是一般情况下都比较适用。
    # 反之，如果卷积层的设置一直变化，将会导致程序不停地做优化，反而会耗费更多的时间
    torch.backends.cudnn.deterministic = True

# 模型保存
def save_state(model, best_acc):
    print('==> Saving model ...')
    state = {
            'best_acc': best_acc,
            'state_dict': model.state_dict(),
            }
    state_copy = state['state_dict'].copy()
    for key in state_copy.keys():
        if 'module' in key:
            state['state_dict'][key.replace('module.', '')] = \
                    state['state_dict'].pop(key)
    torch.save(state, 'models_save/nin_gc.pth')
    #torch.save(state, 'models_save/nin.pth')
    #torch.save(state, 'models_save/nin_gc_bn_gama.pth')

# 模型训练
def train(epoch):
    model.train()

    for batch_idx, (data, target) in enumerate(trainloader):
        # W量化（三值或二值）
        if args.W == 2 or args.W == 3:
            Tnn_Bin_Op.tnn_bin()
        
        # 前向传播
        data, target = Variable(data.cuda()), Variable(target.cuda())
        output = model(data)
        loss = criterion(output, target)

        # 反向传播
        optimizer.zero_grad()
        loss.backward()

        if args.W == 2 or args.W == 3:
            Tnn_Bin_Op.restore() # 恢复浮点W
            if args.W == 2:
                Tnn_Bin_Op.updateBinaryGradWeight()# α（缩放因子） ——> grad
        
        optimizer.step() # 参数更新

        # 显示训练集loss(/100个batch)
        if batch_idx % 100 == 0:
            print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}\tLR: {}'.format(
                epoch, batch_idx * len(data), len(trainloader.dataset),
                100. * batch_idx / len(trainloader), loss.data.item(),
                optimizer.param_groups[0]['lr']))
    return

# 模型测试
def test():
    global best_acc
    model.eval()
    test_loss = 0
    correct = 0

    # W量化（三值或二值）
    if args.W == 2 or args.W == 3:
        Tnn_Bin_Op.tnn_bin()

    for data, target in testloader:
        data, target = Variable(data.cuda()), Variable(target.cuda())
        # 前向传播
        output = model(data)
        test_loss += criterion(output, target).data.item()
        pred = output.data.max(1, keepdim=True)[1]
        correct += pred.eq(target.data.view_as(pred)).cpu().sum()

    if args.W == 2 or args.W == 3:
        Tnn_Bin_Op.restore()# 恢复浮点W
    # 测试准确率
    acc = 100. * float(correct) / len(testloader.dataset)

    # 最优准确率及model保存
    if acc > best_acc:
        best_acc = acc
        save_state(model, best_acc)
    test_loss /= len(testloader.dataset)

    # 显示测试集损失、准确率
    print('\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.2f}%)'.format(
        test_loss * 256., correct, len(testloader.dataset),
        100. * float(correct) / len(testloader.dataset)))

    # 显示测试集最优准确率
    print('Best Accuracy: {:.2f}%\n'.format(best_acc))
    return

# 训练lr调整
def adjust_learning_rate(optimizer, epoch):
    update_list = [80, 130, 180, 230, 280]    # Wb
    #update_list = [70, 110, 150, 190, 230]    # Wt
    if epoch in update_list:
        for param_group in optimizer.param_groups:
            param_group['lr'] = param_group['lr'] * 0.1
    return

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    # cpu、gpu
    # 只有cpu可用的时候设置为true
    parser.add_argument('--cpu', action='store_true',
            help='set if only CPU is available')
    # dataset
    # 数据所在的路径
    parser.add_argument('--data', action='store', default='../data',
            help='dataset path')
    # lr
    # 学习率，默认为0.01
    parser.add_argument('--lr', action='store', default=0.01,
            help='the intial learning rate')
    # weight_dacay
    # 权重惩罚项，默认为0，即不惩罚
    parser.add_argument('--wd', action='store', default=0,
            help='nin_gc:0, nin:1e-5')
    # resume
    # 模型是否从之前保存的模型继续训练？
    parser.add_argument('--resume', default='', type=str, metavar='PATH',
            help='the path to the resume model')
    # refine
    # 模型剪枝
    parser.add_argument('--refine', default='', type=str, metavar='PATH',
            help='the path to the refine(prune) model')
    # evaluate
    # 模型执行前向推理
    parser.add_argument('--evaluate', action='store_true',
            help='evaluate the model')
    # batch_size、num_workers
    # 训练的batch_size
    parser.add_argument('--train_batch_size', type=int, default=50)
    # 前向推理时候的batch_size
    parser.add_argument('--eval_batch_size', type=int, default=256)
    # 程序执行的线程数，默认为2
    parser.add_argument('--num_workers', type=int, default=2)
    # epochs
    # 训练时候的训练轮次
    parser.add_argument('--epochs', type=int, default=300, metavar='N',
            help='number of epochs to train')
    # W/A — FP/三值/二值
    parser.add_argument('--W', type=int, default=2,
            help='Wb:2, Wt:3')
    parser.add_argument('--A', type=int, default=2,
            help='Ab:2, Afp:32')

    args = parser.parse_args()
    print('==> Options:',args)

    setup_seed(1)#随机种子——训练结果可复现

    print('==> Preparing data..')
    # 数据增强
    # 训练集：随机裁剪 + 水平翻转 + 归一化
    transform_train = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        # 随机水平翻转
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        # R,G,B每层的归一化用到的均值和方差
        transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010))])
    # 测试集：归一化
    transform_test = transforms.Compose([
        transforms.ToTensor(),
        # R,G,B每层的归一化用到的均值和方差
        transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010))])

    # 数据加载
    trainset = torchvision.datasets.CIFAR10(root = args.data, train = True, download = True, transform = transform_train)
    trainloader = torch.utils.data.DataLoader(trainset, batch_size=args.train_batch_size, shuffle=True, num_workers=args.num_workers) # 训练集数据

    testset = torchvision.datasets.CIFAR10(root = args.data, train = False, download = True, transform = transform_test)
    testloader = torch.utils.data.DataLoader(testset, batch_size=args.eval_batch_size, shuffle=False, num_workers=args.num_workers) # 测试集数据

    # cifar10类别
    classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')

    # model
    if args.refine:
        print('******Refine model******')
        #checkpoint = torch.load('../prune/models_save/nin_refine.pth')
        # 加载模型
        checkpoint = torch.load(args.refine)

        model = nin_gc.Net(cfg=checkpoint['cfg'], A=args.A)
        #model = nin.Net(cfg=checkpoint['cfg'], A=args.A)
        model.load_state_dict(checkpoint['state_dict'])
        best_acc = 0
    else:
        print('******Initializing model******')
        model = nin_gc.Net(A=args.A)
        #model = nin.Net(A=args.A)
        #model = nin_bn_conv.Net()
        best_acc = 0
        for m in model.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.xavier_uniform_(m.weight.data)
                m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                m.weight.data.normal_(0, 0.01)
                m.bias.data.zero_()
    if args.resume:
        print('******Reume model******')
        #pretrained_model = torch.load('models_save/nin_gc.pth')
        pretrained_model = torch.load(args.resume)
        best_acc = pretrained_model['best_acc']
        model.load_state_dict(pretrained_model['state_dict'])

    # cpu、gpu
    if not args.cpu:
        model.cuda()
        model = torch.nn.DataParallel(model, device_ids=range(torch.cuda.device_count()))# gpu并行训练
    # 打印模型结构
    print(model)

    # 超参数
    base_lr = float(args.lr)
    param_dict = dict(model.named_parameters())
    params = []
    for key, value in param_dict.items():
        params += [{'params':[value], 'lr': base_lr, 'weight_decay':args.wd}]

    # 损失函数
    criterion = nn.CrossEntropyLoss()
    # 优化器
    optimizer = optim.Adam(params, lr=base_lr, weight_decay=args.wd)
    
    # 量化（三值或二值）实例化
    if args.W == 2 or args.W == 3:
        Tnn_Bin_Op = util_w_t_b.Tnn_Bin_Op(model, W=args.W)
        #Tnn_Bin_Op = util_w_t_gap.Tnn_Bin_Op(model)
    # 测试模型
    if args.evaluate:
        test()
        exit(0)

    # 训练模型
    for epoch in range(1, args.epochs):
        adjust_learning_rate(optimizer, epoch)
        train(epoch)
        test()
