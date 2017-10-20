import numpy as np

import chainer
import chainer.functions as F
import chainer.links as L
from chainer.links.model.vision.resnet import ResNet101Layers
from chainer.links.model.vision.resnet import ResNet50Layers

from chainercv.links.model.faster_rcnn.faster_rcnn import FasterRCNN
from chainercv.links.model.faster_rcnn.region_proposal_network import \
    RegionProposalNetwork
from chainercv.utils import download_model


def copy_persistent_link(dst, src):
    for name in dst._persistent:
        d = dst.__dict__[name]
        s = src.__dict__[name]
        if isinstance(d, np.ndarray):
            d[:] = s
        elif isinstance(d, int):
            d = s
        else:
            raise ValueError


def copy_persistent_chain(dst, src):
    copy_persistent_link(dst, src)
    for l in dst.children():
        name = l.name
        if (isinstance(dst.__dict__[name], chainer.Chain) and
                isinstance(src.__dict__[name], chainer.Chain)):
            copy_persistent_chain(dst.__dict__[name], src.__dict__[name])
        elif (isinstance(dst.__dict__[name], chainer.Link) and
                isinstance(src.__dict__[name], chainer.Link)):
            copy_persistent_link(dst.__dict__[name], src.__dict__[name])


class FasterRCNNResNet(FasterRCNN):

    """Faster R-CNN based on VGG-16.

    When you specify the path of a pre-trained chainer model serialized as
    a :obj:`.npz` file in the constructor, this chain model automatically
    initializes all the parameters with it.
    When a string in prespecified set is provided, a pretrained model is
    loaded from weights distributed on the Internet.
    The list of pretrained models supported are as follows:

    * :obj:`voc07`: Loads weights trained with the trainval split of \
        PASCAL VOC2007 Detection Dataset.
    * :obj:`imagenet`: Loads weights trained with ImageNet Classfication \
        task for the feature extractor and the head modules. \
        Weights that do not have a corresponding layer in VGG-16 \
        will be randomly initialized.

    For descriptions on the interface of this model, please refer to
    :class:`chainercv.links.model.faster_rcnn.FasterRCNN`.

    :obj:`FasterRCNNVGG16` supports finer control on random initializations of
    weights by arguments
    :obj:`vgg_initialW`, :obj:`rpn_initialW`, :obj:`loc_initialW` and
    :obj:`score_initialW`.
    It accepts a callable that takes an array and edits its values.
    If :obj:`None` is passed as an initializer, the default initializer is
    used.

    Args:
        n_fg_class (int): The number of classes excluding the background.
        pretrained_model (str): The destination of the pre-trained
            chainer model serialized as a :obj:`.npz` file.
            If this is one of the strings described
            above, it automatically loads weights stored under a directory
            :obj:`$CHAINER_DATASET_ROOT/pfnet/chainercv/models/`,
            where :obj:`$CHAINER_DATASET_ROOT` is set as
            :obj:`$HOME/.chainer/dataset` unless you specify another value
            by modifying the environment variable.
        min_size (int): A preprocessing paramter for :meth:`prepare`.
        max_size (int): A preprocessing paramter for :meth:`prepare`.
        ratios (list of floats): This is ratios of width to height of
            the anchors.
        anchor_scales (list of numbers): This is areas of anchors.
            Those areas will be the product of the square of an element in
            :obj:`anchor_scales` and the original area of the reference
            window.
        vgg_initialW (callable): Initializer for the layers corresponding to
            the VGG-16 layers.
        rpn_initialW (callable): Initializer for Region Proposal Network
            layers.
        loc_initialW (callable): Initializer for the localization head.
        score_initialW (callable): Initializer for the score head.
        proposal_creator_params (dict): Key valued paramters for
            :obj:`chainercv.links.model.faster_rcnn.ProposalCreator`.

    """

    _models = {}
    feat_stride = 16

    def __init__(self,
                 resnet_name,
                 n_fg_class=None,
                 pretrained_model=None,
                 min_size=600, max_size=1000,
                 ratios=[0.5, 1, 2], anchor_scales=[8, 16, 32],
                 res_initialW=None, rpn_initialW=None,
                 loc_initialW=None, score_initialW=None,
                 proposal_creator_params=dict(),
                 roi_align=False, res5_stride=2,
                 ):
        if n_fg_class is None:
            if pretrained_model not in self._models:
                raise ValueError(
                    'The n_fg_class needs to be supplied as an argument')
            n_fg_class = self._models[pretrained_model]['n_fg_class']

        if loc_initialW is None:
            loc_initialW = chainer.initializers.Normal(0.001)
        if score_initialW is None:
            score_initialW = chainer.initializers.Normal(0.01)
        if rpn_initialW is None:
            rpn_initialW = chainer.initializers.Normal(0.01)
        if res_initialW is None and pretrained_model:
            res_initialW = chainer.initializers.constant.Zero()

        if resnet_name == 'resnet50':
            self._resnet_layers = ResNet50Layers
        elif resnet_name == 'resnet101':
            self._resnet_layers = ResNet101Layers
        else:
            raise ValueError

        class ResNet(self._resnet_layers):

            def __call__(self, x):
                with chainer.using_config('train', False):
                    out = super(ResNet, self).__call__(x, layers=['res4'])
                return out['res4']

        # TODO(wkentaro): Use PickableSequentialChain.
        extractor = ResNet(pretrained_model=None)
        # extractor = ResNet50(initialW=res_initialW)
        # extractor.pick = 'res5'
        # # Delete all layers after conv5_3.
        # extractor.remove_unused()
        rpn = RegionProposalNetwork(
            1024, 512,
            ratios=ratios,
            anchor_scales=anchor_scales,
            feat_stride=self.feat_stride,
            initialW=rpn_initialW,
            proposal_creator_params=proposal_creator_params,
        )
        head = ResNetRoIHead(
            n_fg_class + 1,
            roi_size=7, spatial_scale=1. / self.feat_stride,
            res_initialW=res_initialW,
            loc_initialW=loc_initialW,
            score_initialW=score_initialW,
            roi_align=roi_align,
            res5_stride=res5_stride,
        )

        super(FasterRCNNResNet, self).__init__(
            extractor,
            rpn,
            head,
            mean=np.array([123.152, 115.903, 103.063],
                          dtype=np.float32)[:, None, None],
            min_size=min_size,
            max_size=max_size
        )

        if pretrained_model in self._models:
            path = download_model(self._models[pretrained_model]['url'])
            chainer.serializers.load_npz(path, self)
        elif pretrained_model == 'imagenet':
            self._copy_imagenet_pretrained_resnet()
        elif pretrained_model:
            chainer.serializers.load_npz(pretrained_model, self)

    def _copy_imagenet_pretrained_resnet(self):
        pretrained_model = self._resnet_layers(pretrained_model='auto')

        self.extractor.conv1.copyparams(pretrained_model.conv1)
        # The pretrained weights are trained to accept BGR images.
        # Convert weights so that they accept RGB images.
        self.extractor.conv1.W.data[:] = \
            self.extractor.conv1.W.data[:, ::-1]

        self.extractor.bn1.copyparams(pretrained_model.bn1)
        copy_persistent_chain(self.extractor.bn1, pretrained_model.bn1)

        self.extractor.res2.copyparams(pretrained_model.res2)
        copy_persistent_chain(self.extractor.res2, pretrained_model.res2)

        self.extractor.res3.copyparams(pretrained_model.res3)
        copy_persistent_chain(self.extractor.res3, pretrained_model.res3)

        self.extractor.res4.copyparams(pretrained_model.res4)
        copy_persistent_chain(self.extractor.res4, pretrained_model.res4)

        self.head.res5.copyparams(pretrained_model.res5)
        copy_persistent_chain(self.head.res5, pretrained_model.res5)


class ResNetRoIHead(chainer.Chain):

    """Faster R-CNN Head for VGG-16 based implementation.

    This class is used as a head for Faster R-CNN.
    This outputs class-wise localizations and classification based on feature
    maps in the given RoIs.

    Args:
        n_class (int): The number of classes possibly including the background.
        roi_size (int): Height and width of the feature maps after RoI-pooling.
        spatial_scale (float): Scale of the roi is resized.
        vgg_initialW (callable): Initializer for the layers corresponding to
            the VGG-16 layers.
        loc_initialW (callable): Initializer for the localization head.
        score_initialW (callable): Initializer for the score head.

    """

    def __init__(self, n_class, roi_size, spatial_scale,
                 res_initialW=None, loc_initialW=None, score_initialW=None,
                 roi_align=False, res5_stride=2):
        # n_class includes the background
        super(ResNetRoIHead, self).__init__()
        with self.init_scope():
            from chainer.links.model.vision.resnet import BuildingBlock
            self.res5 = BuildingBlock(
                3, 1024, 512, 2048, stride=res5_stride, initialW=res_initialW)
            self.cls_loc = L.Linear(2048, n_class * 4, initialW=loc_initialW)
            self.score = L.Linear(2048, n_class, initialW=score_initialW)

        self.n_class = n_class
        self.roi_size = roi_size
        self.spatial_scale = spatial_scale
        self._roi_align = roi_align

    def __call__(self, x, rois, roi_indices):
        """Forward the chain.

        We assume that there are :math:`N` batches.

        Args:
            x (~chainer.Variable): 4D image variable.
            rois (array): A bounding box array containing coordinates of
                proposal boxes.  This is a concatenation of bounding box
                arrays from multiple images in the batch.
                Its shape is :math:`(R', 4)`. Given :math:`R_i` proposed
                RoIs from the :math:`i` th image,
                :math:`R' = \\sum _{i=1} ^ N R_i`.
            roi_indices (array): An array containing indices of images to
                which bounding boxes correspond to. Its shape is :math:`(R',)`.

        """
        roi_indices = roi_indices.astype(np.float32)
        indices_and_rois = self.xp.concatenate(
            (roi_indices[:, None], rois), axis=1)
        pool = _roi_pooling_2d_yx(
            x, indices_and_rois, self.roi_size, self.roi_size,
            self.spatial_scale, self._roi_align)

        with chainer.using_config('train', False):
            res5 = self.res5(pool)
        from chainer.links.model.vision.resnet import \
            _global_average_pooling_2d
        pool5 = _global_average_pooling_2d(res5)
        roi_cls_locs = self.cls_loc(pool5)
        roi_scores = self.score(pool5)
        return roi_cls_locs, roi_scores


def _roi_pooling_2d_yx(x, indices_and_rois, outh, outw, spatial_scale,
                       roi_align=False):
    xy_indices_and_rois = indices_and_rois[:, [0, 2, 1, 4, 3]]
    func = F.roi_align_2d if roi_align else F.roi_pooling_2d
    pool = func(x, xy_indices_and_rois, outh, outw, spatial_scale)
    return pool


class FasterRCNNResNet50(FasterRCNNResNet):

    def __init__(self, *args, **kwargs):
        return super(FasterRCNNResNet50, self).__init__(
            'resnet50', *args, **kwargs)


class FasterRCNNResNet101(FasterRCNNResNet):

    def __init__(self, *args, **kwargs):
        return super(FasterRCNNResNet101, self).__init__(
            'resnet101', *args, **kwargs)
