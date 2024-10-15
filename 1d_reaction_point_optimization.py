import time
import os
import torch
import torch.nn as nn
import matplotlib.pyplot as plt
import random
from torch.optim import LBFGS
from tqdm import tqdm
import argparse
from util import *
from model_dict import get_model

seed = 0
np.random.seed(seed)
random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)

parser = argparse.ArgumentParser('Training Point Optimization')
parser.add_argument('--model', type=str, default='pinn')
parser.add_argument('--device', type=str, default='cuda:0')
args = parser.parse_args()
device = args.device

res, b_left, b_right, b_upper, b_lower = get_data([0, 2 * np.pi], [0, 1], 101, 101)
res_test, _, _, _, _ = get_data([0, 2 * np.pi], [0, 1], 101, 101)

res = torch.tensor(res, dtype=torch.float32, requires_grad=True).to(device)
b_left = torch.tensor(b_left, dtype=torch.float32, requires_grad=True).to(device)
b_right = torch.tensor(b_right, dtype=torch.float32, requires_grad=True).to(device)
b_upper = torch.tensor(b_upper, dtype=torch.float32, requires_grad=True).to(device)
b_lower = torch.tensor(b_lower, dtype=torch.float32, requires_grad=True).to(device)

x_res, t_res = res[:, 0:1], res[:, 1:2]
x_left, t_left = b_left[:, 0:1], b_left[:, 1:2]
x_right, t_right = b_right[:, 0:1], b_right[:, 1:2]
x_upper, t_upper = b_upper[:, 0:1], b_upper[:, 1:2]
x_lower, t_lower = b_lower[:, 0:1], b_lower[:, 1:2]


def init_weights(m):
    if isinstance(m, nn.Linear):
        torch.nn.init.xavier_uniform(m.weight)
        m.bias.data.fill_(0.01)


if args.model == 'KAN':
    model = get_model(args).Model(width=[2, 5, 1], grid=5, k=3, grid_eps=1.0, \
                                  noise_scale_base=0.25, device=device).to(device)
elif args.model == 'QRes':
    model = get_model(args).Model(in_dim=2, hidden_dim=256, out_dim=1, num_layer=4).to(device)
    model.apply(init_weights)
else:
    model = get_model(args).Model(in_dim=2, hidden_dim=512, out_dim=1, num_layer=4).to(device)
    model.apply(init_weights)

optim = LBFGS(model.parameters(), line_search_fn='strong_wolfe')

print(model)
print(get_n_params(model))
loss_track = []

for i in tqdm(range(1000)):
    def closure():
        pred_res = model(x_res, t_res)
        pred_left = model(x_left, t_left)
        pred_right = model(x_right, t_right)
        pred_upper = model(x_upper, t_upper)
        pred_lower = model(x_lower, t_lower)

        u_x = torch.autograd.grad(pred_res, x_res, grad_outputs=torch.ones_like(pred_res), retain_graph=True,
                                  create_graph=True)[0]
        u_t = torch.autograd.grad(pred_res, t_res, grad_outputs=torch.ones_like(pred_res), retain_graph=True,
                                  create_graph=True)[0]

        loss_res = torch.mean((u_t - 5 * pred_res * (1 - pred_res)) ** 2)
        loss_bc = torch.mean((pred_upper - pred_lower) ** 2)
        loss_ic = torch.mean(
            (pred_left[:, 0] - torch.exp(- (x_left[:, 0] - torch.pi) ** 2 / (2 * (torch.pi / 4) ** 2))) ** 2)

        loss_track.append([loss_res.item(), loss_bc.item(), loss_ic.item()])

        loss = loss_res + loss_bc + loss_ic
        optim.zero_grad()
        loss.backward()
        return loss


    optim.step(closure)

print('Loss Res: {:4f}, Loss_BC: {:4f}, Loss_IC: {:4f}'.format(loss_track[-1][0], loss_track[-1][1], loss_track[-1][2]))
print('Train Loss: {:4f}'.format(np.sum(loss_track[-1])))

if not os.path.exists('./results/'):
    os.makedirs('./results/')
torch.save(model.state_dict(), f'./results/1dreaction_{args.model}_point.pt')

# Visualize
res_test = torch.tensor(res_test, dtype=torch.float32, requires_grad=True).to(device)
x_test, t_test = res_test[:, 0:1], res_test[:, 1:2]

with torch.no_grad():
    pred = model(x_test, t_test)[:, 0:1]
    pred = pred.cpu().detach().numpy()

pred = pred.reshape(101, 101)


def h(x):
    return np.exp(- (x - np.pi) ** 2 / (2 * (np.pi / 4) ** 2))


def u_ana(x, t):
    return h(x) * np.exp(5 * t) / (h(x) * np.exp(5 * t) + 1 - h(x))


res_test, _, _, _, _ = get_data([0, 2 * np.pi], [0, 1], 101, 101)
u = u_ana(res_test[:, 0], res_test[:, 1]).reshape(101, 101)

rl1 = np.sum(np.abs(u - pred)) / np.sum(np.abs(u))
rl2 = np.sqrt(np.sum((u - pred) ** 2) / np.sum(u ** 2))

print('relative L1 error: {:4f}'.format(rl1))
print('relative L2 error: {:4f}'.format(rl2))

plt.figure(figsize=(4, 3))
plt.imshow(pred, aspect='equal')
plt.xlabel('x')
plt.ylabel('t')
plt.title('Predicted u(x,t)')
plt.colorbar()
plt.tight_layout()
plt.axis('off')
plt.savefig(f'./results/1dreaction_{args.model}_point_optimization_pred.pdf', bbox_inches='tight')

plt.figure(figsize=(4, 3))
plt.imshow(u, aspect='equal')
plt.xlabel('x')
plt.ylabel('t')
plt.title('Exact u(x,t)')
plt.colorbar()
plt.tight_layout()
plt.axis('off')
plt.savefig('./results/1dreaction_exact.pdf', bbox_inches='tight')

plt.figure(figsize=(4, 3))
plt.imshow(pred - u, aspect='equal', cmap='coolwarm', vmin=-0.15, vmax=0.15)
plt.xlabel('x')
plt.ylabel('t')
plt.title('Absolute Error')
plt.colorbar()
plt.tight_layout()
plt.axis('off')
plt.savefig(f'./results/1dreaction_{args.model}_point_optimization_error.pdf', bbox_inches='tight')
