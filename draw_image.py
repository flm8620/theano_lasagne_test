from __future__ import print_function

import argparse

import numpy as np

import theano
import theano.tensor as T
import lasagne

import load_data
import model_io

try:
    import PIL.Image as Image
except ImportError:
    import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", help="model name", choices=['cifar', 'lenet'])
    parser.add_argument("model_file", help="model file")
    parser.add_argument('layer', help='layer name to get image output')
    parser.add_argument('imageID', help='ID of image for input', type=int)
    parser.add_argument('-d', '--dataset', choices=['train', 'val', 'test'], default='test')
    parser.add_argument('--no-separate', help='split the data', action='store_true')
    parser.add_argument('--first-part', help='take first part of data instead of the second', action='store_true')
    parser.add_argument('-i', '--input', help='only get input image', action='store_true')
    parser.add_argument('-w', '--draw-weights', help='only draw weights, give the width of kernel', action='store_true')

    args = parser.parse_args()

    model = args.model
    batch_size = 1
    separate = not args.no_separate
    model_file = args.model_file
    layer_name = args.layer
    chosen_set = args.dataset
    load_first_part = args.first_part
    imageID = args.imageID
    only_input = args.input
    only_weights = args.draw_weights
    if not only_weights:
        filename = str(imageID) + '_' + model + '_' + layer_name + '_output.png'
    else:
        filename = 'weight_' + model + '_' + layer_name + '_output.png'
    print('--Parameters--')
    print('  model         : ', model)
    print('  layer name    : ', layer_name)
    print('  batch_size    : ', batch_size)
    print('  model_file    : ', model_file)
    print('  middle output images will be saved to : ', filename)
    print('  separate data :', separate)
    if separate:
        print('    take first or second part of data :', 'first' if load_first_part else 'second')
    print('batch_size=', batch_size)

    if separate:
        nOutput = 5
    else:
        nOutput = 10

    # Load the dataset
    print("Loading data...")
    if not only_weights:
        if only_input:
            X_train, y_train, X_val, y_val, X_test, y_test = load_data.load_dataset(model, separate, load_first_part,
                                                                                    substract_mean=False)
        else:
            X_train, y_train, X_val, y_val, X_test, y_test = load_data.load_dataset(model, separate, load_first_part)

        print(len(X_train), 'train images')
        print(len(X_val), 'val images')
        print(len(X_test), 'test images')

        print('getting from' + chosen_set)
        if chosen_set == 'train':
            X_set = X_train
            y_set = y_train
        elif chosen_set == 'val':
            X_set = X_val
            y_set = y_val
        else:
            X_set = X_test
            y_set = y_test

        if only_input:
            image_data = X_set[imageID]
            if model == 'cifar':
                image_data = image_data.reshape((3, 32, 32))
                image_data = np.rollaxis(image_data, 0, 3) # 3 32 32 to 32 32 3
            else:
                image_data = image_data.reshape((28, 28))
            image_data *= 255
            image_data = image_data.astype('uint8')
            image = Image.fromarray(image_data)
            image.save(filename)
            print('image saved to :', filename)
            exit()

    # Prepare Theano variables for inputs and targets
    input_var = T.tensor4('inputs')

    # Create neural network model (depending on first command line parameter)
    print("Building model and compiling functions...")
    net, net_output = model_io.load_model(model, model_file, nOutput, input_var)

    if not only_weights:
        print("Getting middle output...")

        output = lasagne.layers.get_output(net[layer_name])
        get_output_image = theano.function([input_var], output.flatten(3))

        output_shape = np.array(lasagne.layers.get_output_shape(net[layer_name]))
        foo, nKernel, h, w = output_shape
        print('layer ' + layer_name + ' shape :', output_shape)

        batch_output = get_output_image(np.array([X_set[imageID]]))
        images_output = batch_output[0]
        prediction = lasagne.layers.get_output(net_output)

        get_pred = theano.function([input_var], prediction)
        pred = get_pred(np.array([X_set[imageID]]))
    else:
        if model == 'cifar':
            weights = net[layer_name].W.get_value()
            print('weights shape :', weights.shape)
            nKernel, foo, h, w = weights.shape
            assert foo == 3
            flatten_w = net[layer_name].W.flatten(3)
            images_output = flatten_w.eval()
            images_output = np.rollaxis(images_output, 1, 0)  # nKernel 3 w*h to 3 nKernel w*h
            print('flatten weights shape :', images_output.shape)
        else:
            weights = net[layer_name].W.get_value()
            print('weights shape :', weights.shape)
            nKernel, foo, h, w = weights.shape
            assert foo == 1
            flatten_w = net[layer_name].W.flatten(2)
            images_output = flatten_w.eval()
            print('flatten weights shape :', images_output.shape)



    width = 1
    while width * width < nKernel:
        width += 1

    if width * width > nKernel:
        if images_output.ndim == 2:
            images_output = np.concatenate((images_output, np.zeros((width * width - nKernel, w * h))), axis=0)
        elif images_output.ndim == 3:
            images_output = np.concatenate((images_output, np.zeros((3, width * width - nKernel, w * h))), axis=1)
        else:
            assert False

    image = Image.fromarray(tile_raster_images(
        X=images_output,  # chose batch 0
        img_shape=(h, w), tile_shape=(width, width),
        tile_spacing=(1, 1)))
    image.save(filename)
    print('image saved to :', filename)


def scale_to_unit_interval(ndar, eps=1e-8):
    """ Scales all values in the ndarray ndar to be between 0 and 1 """
    ndar = ndar.copy()
    ndar -= ndar.min()
    ndar *= 1.0 / (ndar.max() + eps)
    return ndar


def tile_raster_images(X, img_shape, tile_shape, tile_spacing=(0, 0),
                       scale_rows_to_unit_interval=True,
                       output_pixel_vals=True):
    """
    Transform an array with one flattened image per row, into an array in
    which images are reshaped and layed out like tiles on a floor.

    This function is useful for visualizing datasets whose rows are images,
    and also columns of matrices for transforming those rows
    (such as the first layer of a neural net).

    :type X: a 2-D ndarray or a tuple of 4 channels, elements of which can
    be 2-D ndarrays or None;
    :param X: a 2-D array in which every row is a flattened image.

    :type img_shape: tuple; (height, width)
    :param img_shape: the original shape of each image

    :type tile_shape: tuple; (rows, cols)
    :param tile_shape: the number of images to tile (rows, cols)

    :param output_pixel_vals: if output should be pixel values (i.e. int8
    values) or floats

    :param scale_rows_to_unit_interval: if the values need to be scaled before
    being plotted to [0,1] or not


    :returns: array suitable for viewing as an image.
    (See:`Image.fromarray`.)
    :rtype: a 2-d array with same dtype as X.

    """

    assert len(img_shape) == 2
    assert len(tile_shape) == 2
    assert len(tile_spacing) == 2

    # The expression below can be re-written in a more C style as
    # follows :
    #
    # out_shape    = [0,0]
    # out_shape[0] = (img_shape[0]+tile_spacing[0])*tile_shape[0] -
    #                tile_spacing[0]
    # out_shape[1] = (img_shape[1]+tile_spacing[1])*tile_shape[1] -
    #                tile_spacing[1]
    out_shape = [
        (ishp + tsp) * tshp - tsp
        for ishp, tshp, tsp in zip(img_shape, tile_shape, tile_spacing)
        ]

    #if isinstance(X, tuple):
    if X.ndim == 3: #RGB
        # Create an output np ndarray to store the image
        if output_pixel_vals:
            out_array = np.zeros((out_shape[0], out_shape[1], 3),
                                 dtype='uint8')
        else:
            out_array = np.zeros((out_shape[0], out_shape[1], 3),
                                 dtype=X.dtype)

        # colors default to 0, alpha defaults to 1 (opaque)
        if output_pixel_vals:
            channel_defaults = [0, 0, 0, 255]
        else:
            channel_defaults = [0., 0., 0., 1.]

        for i in range(3):
            assert X[i] is not None
            if X[i] is None:
                # if channel is None, fill it with zeros of the correct
                # dtype
                dt = out_array.dtype
                if output_pixel_vals:
                    dt = 'uint8'
                out_array[:, :, i] = np.zeros(
                    out_shape,
                    dtype=dt
                ) + channel_defaults[i]
            else:
                # use a recurrent call to compute the channel and store it
                # in the output
                out_array[:, :, i] = tile_raster_images(
                    X[i], img_shape, tile_shape, tile_spacing,
                    scale_rows_to_unit_interval, output_pixel_vals)
        return out_array

    else:
        # if we are dealing with only one channel
        H, W = img_shape
        Hs, Ws = tile_spacing

        # generate a matrix to store the output
        dt = X.dtype
        if output_pixel_vals:
            dt = 'uint8'
        out_array = np.zeros(out_shape, dtype=dt)

        for tile_row in range(tile_shape[0]):
            for tile_col in range(tile_shape[1]):
                if tile_row * tile_shape[1] + tile_col < X.shape[0]:
                    this_x = X[tile_row * tile_shape[1] + tile_col]
                    if scale_rows_to_unit_interval:
                        # if we should scale values to be between 0 and 1
                        # do this by calling the `scale_to_unit_interval`
                        # function
                        this_img = scale_to_unit_interval(
                            this_x.reshape(img_shape))
                    else:
                        this_img = this_x.reshape(img_shape)
                    # add the slice to the corresponding position in the
                    # output array
                    c = 1
                    if output_pixel_vals:
                        c = 255
                    out_array[
                    tile_row * (H + Hs): tile_row * (H + Hs) + H,
                    tile_col * (W + Ws): tile_col * (W + Ws) + W
                    ] = this_img * c
        return out_array


if __name__ == '__main__':
    main()
