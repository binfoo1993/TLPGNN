import argparse, time
import numpy as np
import networkx as nx
import torch as th
import torch.nn as nn
import torch.nn.functional as F
import torch.cuda.profiler as profiler
import scipy.sparse as sp
from torch.utils.cpp_extension import load_inline

def read_data(dataset):
    data_path = "../data/" + dataset + "/"
    ret = {}
    ret['features'] = np.load(data_path+'features.npy')
    ret['graph'] = sp.load_npz(data_path+'csr.npz').tocsc()
    ret['graph'].sort_indices()
    return ret

cpp_source = '''
#include <vector>


std::vector<torch::Tensor> sage_conv_cuda_forward(
        torch::Tensor features,
        torch::Tensor col_starts,
        torch::Tensor rows);

std::vector<torch::Tensor> sage_conv_cuda_backward(
        torch::Tensor features,
        torch::Tensor grad,
        torch::Tensor indegs,
        torch::Tensor row_starts,
        torch::Tensor cols);

#define CHECK_CUDA(x) TORCH_CHECK(x.is_cuda(), #x " must be a CUDA tensor")
#define CHECK_CONTIGUOUS(x) TORCH_CHECK(x.is_contiguous(), #x " must be contiguous")
#define CHECK_INPUT(x) CHECK_CUDA(x); CHECK_CONTIGUOUS(x)

std::vector<torch::Tensor> sage_conv_forward(
        torch::Tensor features,
        torch::Tensor col_starts,
        torch::Tensor rows)
{
    CHECK_INPUT(features);
    CHECK_INPUT(col_starts);
    CHECK_INPUT(rows);

    return sage_conv_cuda_forward(features, col_starts, rows);
}

std::vector<torch::Tensor> sage_conv_backward(
        torch::Tensor features,
        torch::Tensor grad,
        torch::Tensor indegs,
        torch::Tensor row_starts,
        torch::Tensor cols)
{
    CHECK_INPUT(features);
    CHECK_INPUT(grad);
    CHECK_INPUT(indegs);
    CHECK_INPUT(row_starts);
    CHECK_INPUT(cols);

    return sage_conv_cuda_backward(features, grad, indegs, row_starts, cols);
}

PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
    m.def("forward", &sage_conv_forward, "Graphsage conv forward (CUDA)");
    m.def("backward", &sage_conv_backward, "Graphsage conv backward (CUDA)");
}
'''

cuda_source = open("kernel.cu").read()

sage_module = load_inline(name="graphsage",
        cpp_sources=[cpp_source],
        cuda_sources=[cuda_source],
        extra_cuda_cflags=['-m 64'],
        verbose=False)


def main(args):
    th.cuda.set_device(args.gpu)

    # load and preprocess dataset
    data = read_data(args.dataset)
    features = th.cuda.FloatTensor(data['features'][:,0:args.size])
    indptr = data['graph'].indptr
    indegs = th.cuda.FloatTensor([indptr[i+1] - indptr[i] for i in range(len(indptr)-1)])
    col_starts = th.cuda.IntTensor(indptr)
    rows = th.cuda.IntTensor(data['graph'].indices)
    row_starts = th.cuda.IntTensor(data['graph'].tocsr().indptr)
    cols = th.cuda.IntTensor(data['graph'].tocsr().indices)

    rst = sage_module.forward(features, col_starts, rows)
    th.cuda.synchronize()

    run_time = 0.0
    for _ in range(10):
        start_run = time.perf_counter()
        sage_module.forward(features, col_starts, rows)
        th.cuda.synchronize()
        run_time += (time.perf_counter() - start_run)

    print('Time (ms): {:.3f}'.format(run_time*1e3/10))
    return '{:.3f}'.format(run_time*1e3/10)
    # print(time.time() - t)
    # t = time.time()
    # rst = sage_module.backward(features, th.ones_like(rst[0]), indegs, row_starts, cols)
    # th.cuda.synchronize()
    # print(time.time() - t)
    # print(rst[0])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--dataset",
            default="citeseer",
            help="which graph data set to process")
    parser.add_argument("-s", "--size",
            help="feature size", type=int, default=32)
    parser.add_argument("-g", "--gpu",
            type=int, default=0, help="gpu")
    args = parser.parse_args()
    print(args)

    main(args)
