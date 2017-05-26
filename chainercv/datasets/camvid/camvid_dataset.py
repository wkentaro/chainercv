import glob
import os
import shutil

import numpy as np

import chainer
from chainer.dataset import download
from chainercv import utils
from chainercv.utils import read_image

root = 'pfnet/chainercv/camvid'
url = 'https://github.com/alexgkendall/SegNet-Tutorial/archive/master.zip'


def get_camvid():
    data_root = download.get_dataset_directory(root)
    download_file_path = utils.cached_download(url)
    if len(glob.glob(os.path.join(data_root, '*'))) != 9:
        utils.extractall(
            download_file_path, data_root, os.path.splitext(url)[1])
    data_dir = os.path.join(data_root, 'SegNet-Tutorial-master/CamVid')
    if os.path.exists(data_dir):
        for fn in glob.glob(os.path.join(data_dir, '*')):
            shutil.move(fn, os.path.join(data_root, os.path.basename(fn)))
        shutil.rmtree(os.path.dirname(data_dir))
    return data_root


class CamVidDataset(chainer.dataset.DatasetMixin):

    """Dataset class for a semantic segmantion task on CamVid `u`_.

    .. _`u`: https://github.com/alexgkendall/SegNet-Tutorial/tree/master/CamVid

    Args:
        data_dir (string): Path to the root of the training data. If this is
            :obj:`auto`, this class will automatically download data for you
            under :obj:`$CHAINER_DATASET_ROOT/pfnet/chainercv/camvid`.
        mode ({'train', 'val', 'test'}): Select from dataset splits used
            in VOC.

    """

    def __init__(self, data_dir='auto', mode='train'):
        if mode not in ['train', 'val', 'test']:
            raise ValueError(
                'Please pick mode from \'train\', \'val\', \'test\'')

        if data_dir == 'auto':
            data_dir = get_camvid()

        img_list_filename = os.path.join(data_dir, '{}.txt'.format(mode))
        self.filenames = [
            [os.path.join(data_dir, fn.replace('/SegNet/CamVid/', ''))
             for fn in line.split()] for line in open(img_list_filename)]

    def __len__(self):
        return len(self.filenames)

    def get_example(self, i):
        """Returns the i-th example.

        Returns a color image and a label image. Both of them are in CHW
        format.

        Args:
            i (int): The index of the example.

        Returns:
            tuple of color image and label whose shapes are (3, H, W) and
            (1, H, W) respectively. H and W are height and width of the
            images. The dtype of the color image is :obj:`numpy.float32` and
            the dtype of the label image is :obj:`numpy.int32`.

        """
        if i >= len(self):
            raise IndexError('index is too large')
        image_fn, label_fn = self.filenames[i]
        img = read_image(image_fn, color=True)
        label_map = read_image(label_fn, dtype=np.int32, color=False)[0]
        return img, label_map
