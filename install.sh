#!/bin/bash

set -e
set -x

if [ ! -e ~/.anaconda2/envs/faster_rcnn ]; then
  set +x
  source ~/.anaconda2/bin/activate
  set -x

  conda create -q -y --name=faster_rcnn python=2.7
fi

set +x
source ~/.anaconda2/bin/activate faster_rcnn
set -x

conda info -e

conda install -q -y -c menpo opencv

pip install Cython
pip install numpy

pip install -e .

set +x
set +e
