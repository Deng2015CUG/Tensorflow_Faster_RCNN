# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import numpy as np
import tensorflow as tf
import os
import sys
sys.path.append('../../')
from data.io import image_preprocess_multi_gpu_aug
from libs.configs import cfgs
from libs.box_utils.boxes_utils import get_horizen_minAreaRectangle


def read_single_example_and_decode(filename_queue):

    # tfrecord_options = tf.python_io.TFRecordOptions(tf.python_io.TFRecordCompressionType.ZLIB)

    # reader = tf.TFRecordReader(options=tfrecord_options)
    reader = tf.TFRecordReader()
    _, serialized_example = reader.read(filename_queue)

    features = tf.parse_single_example(
        serialized=serialized_example,
        features={
            'img_name': tf.FixedLenFeature([], tf.string),
            'img_height': tf.FixedLenFeature([], tf.int64),
            'img_width': tf.FixedLenFeature([], tf.int64),
            'img': tf.FixedLenFeature([], tf.string),
            'gtboxes_and_label': tf.FixedLenFeature([], tf.string),
            'num_objects': tf.FixedLenFeature([], tf.int64)
        }
    )
    img_name = features['img_name']
    img_height = tf.cast(features['img_height'], tf.int32)
    img_width = tf.cast(features['img_width'], tf.int32)
    img = tf.decode_raw(features['img'], tf.uint8)

    img = tf.reshape(img, shape=[img_height, img_width, 3])
    gtboxes_and_label = tf.decode_raw(features['gtboxes_and_label'], tf.int32)
    gtboxes_and_label = tf.reshape(gtboxes_and_label, [-1, 9])
    num_objects = tf.cast(features['num_objects'], tf.int32)
    return img_name, img, gtboxes_and_label, num_objects


def read_and_prepocess_single_img(filename_queue, shortside_len, is_training):

    img_name, img, gtboxes_and_label, num_objects = read_single_example_and_decode(filename_queue)

    img = tf.cast(img, tf.float32)
    if is_training:
        # prob is 0.3: convert to gray
        img = image_preprocess_multi_gpu_aug.random_rgb2gray(img_tensor=img, gtboxes_and_label=gtboxes_and_label)

        # rotate with 0.5 prob. and if rotate, if will random choose a theta from : tf.range(-90, 90+16, delta=15)
        img, gtboxes_and_label = image_preprocess_multi_gpu_aug.random_rotate_img(img_tensor=img,
                                                                                  gtboxes_and_label=gtboxes_and_label)

        img, gtboxes_and_label, img_h, img_w = image_preprocess_multi_gpu_aug.short_side_resize(img_tensor=img,
                                                                                                gtboxes_and_label=gtboxes_and_label,
                                                                                                target_shortside_len=shortside_len,
                                                                                                max_len=cfgs.IMG_MAX_LENGTH)
        img, gtboxes_and_label = image_preprocess_multi_gpu_aug.random_flip_left_right(img_tensor=img,
                                                                                       gtboxes_and_label=gtboxes_and_label)
        img, gtboxes_and_label = image_preprocess_multi_gpu_aug.random_flip_up_dowm(img_tensor=img,
                                                                                    gtboxes_and_label=gtboxes_and_label)

    else:
        img, gtboxes_and_label, img_h, img_w = image_preprocess_multi_gpu_aug.short_side_resize(img_tensor=img,
                                                                                                gtboxes_and_label=gtboxes_and_label,
                                                                                                target_shortside_len=shortside_len)

    gtboxes_and_label = get_horizen_minAreaRectangle(gtboxes_and_label)
    if cfgs.NET_NAME in ['resnet101_v1d', 'resnet50_v1d']:
        img = img / 255. - tf.constant([cfgs.PIXEL_MEAN_])
    else:
        img = img - tf.constant([cfgs.PIXEL_MEAN])  # sub pixel mean at last
    return img_name, img, gtboxes_and_label, num_objects, img_h, img_w


def next_batch(dataset_name, batch_size, shortside_len, is_training):
    '''
    :return:
    img_name_batch: shape(1, 1)
    img_batch: shape:(1, new_imgH, new_imgW, C)
    gtboxes_and_label_batch: shape(1, Num_Of_objects, 5] .each row is [x1, y1, x2, y2, label]
    '''

    if dataset_name not in ['DOAI2019', 'DOTA', 'ship', 'ICDAR2015', 'pascal', 'coco', 'DOTA_TOTAL', 'WIDER']:
        raise ValueError('dataSet name must be in pascal, coco spacenet and ship')

    if is_training:
        pattern = os.path.join('../data/tfrecord', dataset_name + '_train*')
    else:
        pattern = os.path.join('../data/tfrecord', dataset_name + '_test*')

    print('tfrecord path is -->', os.path.abspath(pattern))

    filename_tensorlist = tf.train.match_filenames_once(pattern)
    # filename_tensorlist = tf.Print(filename_tensorlist,
    #                                [tf.shape(filename_tensorlist)], summarize=10, message="record_list-->:")
    filename_queue = tf.train.string_input_producer(filename_tensorlist)

    shortside_len = tf.constant(shortside_len)
    shortside_len = tf.random_shuffle(shortside_len)[0]

    img_name, img, gtboxes_and_label, num_obs, img_h, img_w = read_and_prepocess_single_img(filename_queue,
                                                                                            shortside_len,
                                                                                            is_training=is_training)
    img_name_batch, img_batch, gtboxes_and_label_batch , num_obs_batch, img_h_batch, img_w_batch = \
        tf.train.batch(
                       [img_name, img, gtboxes_and_label, num_obs, img_h, img_w],
                       batch_size=batch_size,
                       capacity=16,
                       num_threads=16,
                       dynamic_pad=True)
    return img_name_batch, img_batch, gtboxes_and_label_batch, num_obs_batch, img_h_batch, img_w_batch


if __name__ == '__main__':
    os.environ["CUDA_VISIBLE_DEVICES"] = '0'
    img_name_batch, img_batch, gtboxes_and_label_batch, num_objects_batch, img_h_batch, img_w_batch = \
        next_batch(dataset_name=cfgs.DATASET_NAME,  # 'pascal', 'coco'
                   batch_size=cfgs.BATCH_SIZE * len(cfgs.GPU_GROUP.strip().split(',')),
                   shortside_len=cfgs.IMG_SHORT_SIDE_LEN,
                   is_training=True)
    gtboxes_and_label = tf.reshape(gtboxes_and_label_batch, [-1, 9])

    init_op = tf.group(
        tf.global_variables_initializer(),
        tf.local_variables_initializer()
    )

    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True

    with tf.Session(config=config) as sess:
        sess.run(init_op)

        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess, coord)

        img_name_batch_, img_batch_, gtboxes_and_label_batch_, num_objects_batch_ \
            = sess.run([img_name_batch, img_batch, gtboxes_and_label_batch, num_objects_batch])

        print(img_name_batch_)
        print(img_batch_.shape)

        coord.request_stop()
        coord.join(threads)
