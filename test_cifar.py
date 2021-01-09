'''Train CIFAR10 with PyTorch.'''
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import torch.backends.cudnn as cudnn

import torchvision
import torchvision.transforms as transforms

import os
import argparse
import numpy as np

from models import *
from models.simple import *
from utils import progress_bar

from DDN import DDN

from art.attacks.evasion import FastGradientMethod
from art.attacks.evasion import ProjectedGradientDescentPyTorch
from art.estimators.classification import PyTorchClassifier

parser = argparse.ArgumentParser(description='PyTorch CIFAR10 Training')
parser.add_argument('--lr', default=0.1, type=float, help='learning rate')
parser.add_argument('--model', default='VGG16', type=str, help='name of the model')
parser.add_argument('--n_data', default=50000, type=int, help='level of verbos')
parser.add_argument('--resume', '-r', action='store_true',
                    help='resume from checkpoint')
args = parser.parse_args()

device = 'cuda' if torch.cuda.is_available() else 'cpu'
best_acc = 0  # best test accuracy
start_epoch = 0  # start from epoch 0 or last checkpoint epoch

# Data
print('==> Preparing data..')
transform_test = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])

testset = torchvision.datasets.CIFAR10(
    root='/fs/vulcan-datasets/CIFAR/', train=False, download=True, transform=transform_test)
testloader = torch.utils.data.DataLoader(
    testset, batch_size=100, shuffle=False, num_workers=2)

classes = ('plane', 'car', 'bird', 'cat', 'deer',
           'dog', 'frog', 'horse', 'ship', 'truck')

resnet_dict = {'18':ResNet18, '34':ResNet34, '50':ResNet50, '101':ResNet101, '152':ResNet152}


def squared_l2_norm(x: torch.Tensor) -> torch.Tensor:
    flattened = x.view(x.shape[0], -1)
    return (flattened ** 2).sum(1)


def l2_norm(x: torch.Tensor) -> torch.Tensor:
    return squared_l2_norm(x).sqrt()


# Model
print('==> Building model..')
net = get_net(args.model)
net = net.to(device)
if device == 'cuda':
    # net = torch.nn.DataParallel(net)
    net = net.cuda()
    cudnn.benchmark = True


print('Number of parameters: %d'%sum(p.numel() for p in net.parameters()))

criterion = nn.CrossEntropyLoss()
optimizer = optim.SGD(net.parameters(), lr=args.lr,
                      momentum=0.9, weight_decay=5e-4)

if args.n_data < 50000:
    checkpoint = torch.load('/vulcanscratch/songweig/ckpts/adv_pool/cifar10/%s_%d.pth'%(args.model, args.n_data))
else:
    checkpoint = torch.load('/vulcanscratch/songweig/ckpts/adv_pool/cifar10/%s.pth'%args.model)
net.load_state_dict(checkpoint['net'])
best_acc = checkpoint['acc']
start_epoch = checkpoint['epoch']


# adv_norm = 0.
# correct = 0
# adv_correct = 0
# total = 0
# for batch_idx, (inputs, targets) in enumerate(testloader):
#     inputs, targets = inputs.to(device), targets.to(device)
#     adv = attacker.attack(net, inputs.to(device), labels=targets.to(device), targeted=False)
#     outputs = net(inputs)
#     _, predicted = outputs.max(1)
#     adv_outputs = net(adv)
#     _, adv_predicted = adv_outputs.max(1)
#     total += targets.size(0)
#     correct += predicted.eq(targets).sum().item()
#     adv_correct += adv_predicted.eq(targets).sum().item()
#     adv_norm += l2_norm(adv - inputs.to(device)).sum().item()
#     progress_bar(batch_idx, len(testloader), 'Adv Acc: %.3f | Acc: %.3f%% (%d/%d)'
#                  % (100.*adv_correct/total, 100.*correct/total, correct, total))


# print('Raw done in error: {:.2f}%.'.format(100.*correct/total))
# print('DDN done in Success: {:.2f}%, Mean L2: {:.4f}.'.format(
#     100.*adv_correct/total,
#     adv_norm/total
# ))


# pred_orig = net(inputs.to(device)).argmax(dim=1).cpu()
# pred_ddn = net(adv).argmax(dim=1).cpu()
# print('Raw done in error: {:.2f}%.'.format(
#     (pred_orig != targets).float().mean().item() * 100,
# ))
# print('DDN done in Success: {:.2f}%, Mean L2: {:.4f}.'.format(
#     (pred_ddn != targets).float().mean().item() * 100,
#     l2_norm(adv - inputs.to(device)).mean().item()
# ))


classifier = PyTorchClassifier(
    model=net,
    loss=criterion,
    optimizer=optimizer,
    clip_values=(0., 1.),
    input_shape=(1, 28, 28),
    nb_classes=10,
)
print("Accuracy on clean test examples: {:.2f}%".format(best_acc))

attack_params = [[2, [0.5, 1, 1.5, 2, 2.5]], [np.inf, [0.05, 0.1, 0.15, 0.2, 0.25]]]
# attack_params = [[2, [1, 2, 3, 4, 5]], [np.inf, [0.1, 0.2, 0.3, 0.4, 0.5]]]
for norm, epsilons in attack_params:
    for epsilon in epsilons:
        attack = FastGradientMethod(estimator=classifier, eps=epsilon, norm=norm)
        # if norm == 2:
        #     attack_PGD = ProjectedGradientDescentPyTorch(estimator=classifier, max_iter=10, batch_size=100, eps_step=1, eps=epsilon, norm=norm)
        # else:
        #     attack_PGD = ProjectedGradientDescentPyTorch(estimator=classifier, max_iter=10, batch_size=100, eps_step=epsilon, eps=epsilon, norm=norm)
        adv_correct = 0
        total = 0
        for batch_idx, (inputs, targets) in enumerate(testloader):
            inputs_adv = attack.generate(x=inputs)
            adv_predicted = classifier.predict(inputs_adv).argmax(1)
            adv_correct += (adv_predicted==targets.numpy()).sum().item()
            total += targets.size(0)
        print("Accuracy on adversarial test examples (L_{:.0f}, eps={:.2f}): {:.2f}%".format(norm, epsilon, 100.*adv_correct/total))