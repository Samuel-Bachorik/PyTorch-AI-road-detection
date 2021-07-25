from os import walk
import os
import numpy
import torch.nn.functional
import torch
os.environ["KMP_DUPLICATE_LIB_OK"]="TRUE"
"""

These classes are made for load images and create augmentation for them.
Augmentation creates new copy of photos and adds blur, tilt, noise and flip to them. 
Thanks to this we have more training data. 
"""


class ImagesLoader:
    def __init__(self, folders_path, height=480, width=640, channel_first=False, file_mask=None, postprocessing=None):
        self.channels = 3
        self.height = height
        self.width = width

        self.postprocessing = postprocessing

        self.file_mask = file_mask

        self.file_names = []
        for folder in folders_path:
            self.file_names = self.file_names + self._find_files(folder)

        self.file_names.sort()

        self.count = len(self.file_names)

        self.channel_first = channel_first

        if self.channel_first:
            self.images = numpy.zeros((self.count, self.channels, self.height, self.width), dtype=numpy.uint8)
        else:
            self.images = numpy.zeros((self.count, self.height, self.width, self.channels), dtype=numpy.uint8)

        ptr = 0
        for file_name in self.file_names:
            print("loading image :", file_name)
            self.images[ptr] = self._load_image(file_name)
            ptr += 1

    def _find_files(self, path):
        files = []
        for (dirpath, dirnames, filenames) in walk(path):
            files.append(filenames)

        result = []
        for file_name in files[0]:
            if file_name.endswith(".jpg") or file_name.endswith(".png"):

                if self.file_mask == None:
                    result.append(path + file_name)
                elif file_name.find(self.file_mask) != -1:
                    result.append(path + file_name)

        return result

    def _load_image(self, file_name):
        image = Image.open(file_name).convert("RGB")

        if self.postprocessing is not None:
            image = self.postprocessing(image)
            image_np = numpy.array(image)
        else:
            image = image.resize((self.width, self.height))
            image_np = numpy.array(image)
            if self.channel_first and len(image_np.shape) > 2:
                image_np = numpy.moveaxis(image_np, 2, 0)

        return image_np






from PIL import Image, ImageFilter
from PIL import Image, ImageEnhance

#height=448, width=640)
class DatasetSegmentation:

    def __init__(self, folders_training, folders_testing, classes_ids, height=480, width=640, augmentation_count=2):

        self.classes_ids = classes_ids

        self.classes_count = len(classes_ids)

        self.height = height
        self.width = width

        self.training_images = []
        self.training_masks = []
        self.training_count = 0

        for folder in folders_training:
            images = ImagesLoader([folder + "/images/"], height, width, channel_first=True)
            masks = ImagesLoader([folder + "/mask/"], height, width, channel_first=True, file_mask="_watershed_mask",
                                 postprocessing=self._mask_postprocessing)

            self.training_images.append(images.images)
            self.training_masks.append(masks.images)

            print("processing augmentation\n")

            images_aug, masks_aug = self._augmentation(images.images, masks.images, augmentation_count)

            self.training_images.append(images_aug)
            self.training_masks.append(masks_aug)

            self.training_count += images.count * (1 + augmentation_count)

        self.testing_images = []
        self.testing_masks = []
        self.testing_count = 0

        for folder in folders_testing:
            images = ImagesLoader([folder + "/images/"], height, width, channel_first=True)
            masks = ImagesLoader([folder + "/mask/"], height, width, channel_first=True, file_mask="_watershed_mask",
                                 postprocessing=self._mask_postprocessing)

            self.testing_images.append(images.images)
            self.testing_masks.append(masks.images)

            self.testing_count += images.count

        self.channels = 3
        self.height = height
        self.width = width
        self.input_shape = (self.channels, self.height, self.width)

        self.output_shape = (self.classes_count, self.height, self.width)
        memory = (self.get_training_count() + self.get_testing_count()) * 2 * numpy.prod(self.input_shape)

        print("\n\n\n\n")
        print("dataset summary : \n")
        print("training_count = ", self.get_training_count())
        print("testing_count  = ", self.get_testing_count())
        print("channels = ", self.channels)
        print("height   = ", self.height)
        print("width    = ", self.width)
        print("classes_count =  ", self.classes_count)
        print("required_memory = ", memory / 1000000, " MB")
        print("\n")

    def get_training_count(self):
        return self.training_count

    def get_testing_count(self):
        return self.testing_count

    def get_training_batch(self, batch_size=32):
        return self._get_batch(self.training_images, self.training_masks, batch_size, True)

    def get_testing_batch(self, batch_size=32):
        return self._get_batch(self.training_images, self.training_masks, batch_size, False)

    def _get_batch(self, images, masks, batch_size, augmentation=False):
        result_x = torch.zeros((batch_size, self.channels, self.height, self.width)).float()
        result_y = torch.zeros((batch_size, self.classes_count, self.height, self.width)).float()

        for i in range(batch_size):
            group_idx = numpy.random.randint(len(images))
            image_idx = numpy.random.randint(len(images[group_idx]))

            image_np = numpy.array(images[group_idx][image_idx]) / 256.0

            mask_np = numpy.array(masks[group_idx][image_idx]).mean(axis=0).astype(int)

            if augmentation:
                image_np = self._augmentation_noise(image_np)
                image_np, mask_np = self._augmentation_flip(image_np, mask_np)

            mask_one_hot = numpy.eye(self.classes_count)[mask_np]
            mask_one_hot = numpy.moveaxis(mask_one_hot, 2, 0)

            result_x[i] = torch.from_numpy(image_np).float()
            result_y[i] = torch.from_numpy(mask_one_hot).float()

        return result_x, result_y

    def _augmentation(self, images, masks, augmentation_count):

        angle_max = 25
        crop_prop = 0.2

        count = images.shape[0]
        total_count = count * augmentation_count

        images_result = numpy.zeros((total_count, images.shape[1], images.shape[2], images.shape[3]), dtype=numpy.uint8)
        mask_result = numpy.zeros((total_count, masks.shape[1], masks.shape[2], masks.shape[3]), dtype=numpy.uint8)

        ptr = 0
        for j in range(count):

            image_in = Image.fromarray(numpy.moveaxis(images[j], 0, 2), 'RGB')
            mask_in = Image.fromarray(numpy.moveaxis(masks[j], 0, 2), 'RGB')

            for i in range(augmentation_count):
                angle = self._rnd(-angle_max, angle_max)

                image_aug = image_in.rotate(angle)
                mask_aug = mask_in.rotate(angle)

                c_left = int(self._rnd(0, crop_prop) * self.width)
                c_top = int(self._rnd(0, crop_prop) * self.height)

                c_right = int(self._rnd(1.0 - crop_prop, 1.0) * self.width)
                c_bottom = int(self._rnd(1.0 - crop_prop, 1.0) * self.height)

                image_aug = image_aug.crop((c_left, c_top, c_right, c_bottom))
                mask_aug = mask_aug.crop((c_left, c_top, c_right, c_bottom))

                if numpy.random.rand() < 0.5:
                    fil = numpy.random.randint(6)

                    if fil == 0:
                        image_aug = image_aug.filter(ImageFilter.BLUR)
                    elif fil == 1:
                        image_aug = image_aug.filter(ImageFilter.EDGE_ENHANCE)
                    elif fil == 2:
                        image_aug = image_aug.filter(ImageFilter.EDGE_ENHANCE_MORE)
                    elif fil == 3:
                        image_aug = image_aug.filter(ImageFilter.SHARPEN)
                    elif fil == 4:
                        image_aug = image_aug.filter(ImageFilter.SMOOTH)
                    elif fil == 5:
                        image_aug = image_aug.filter(ImageFilter.SMOOTH_MORE)

                image_aug = image_aug.resize((self.width, self.height))
                mask_aug = mask_aug.resize((self.width, self.height))

                image_aug = numpy.array(image_aug)
                mask_aug = numpy.array(mask_aug)

                image_aug = numpy.moveaxis(image_aug, 2, 0)
                mask_aug = numpy.moveaxis(mask_aug, 2, 0)

                images_result[ptr] = image_aug
                mask_result[ptr] = mask_aug

                ptr += 1

        return images_result, mask_result

    def _augmentation_noise(self, image_np):
        brightness = self._rnd(-0.25, 0.25)
        contrast = self._rnd(0.5, 1.5)
        noise = 0.05 * (2.0 * numpy.random.rand(self.channels, self.height, self.width) - 1.0)

        result = image_np + brightness
        result = 0.5 + contrast * (result - 0.5)
        result = result + noise

        result = numpy.clip(result, 0.0, 1.0)

        return result

    def _augmentation_flip(self, image_np, mask_np, p=0.2):
        # random flips
        if self._rnd(0, 1) < p:
            image_np = numpy.flip(image_np, axis=1)
            mask_np = numpy.flip(mask_np, axis=0)

        if self._rnd(0, 1) < p:
            image_np = numpy.flip(image_np, axis=2)
            mask_np = numpy.flip(mask_np, axis=1)

        '''
        #random rolling
        if self._rnd(0, 1) < p:
            r           = numpy.random.randint(-32, 32)
            image_np    = numpy.roll(image_np, r, axis=1)
            mask_np     = numpy.roll(mask_np, r, axis=0)
        if self._rnd(0, 1) < p:
            r           = numpy.random.randint(-32, 32)
            image_np    = numpy.roll(image_np, r, axis=2)
            mask_np     = numpy.roll(mask_np, r, axis=1)
        '''

        return image_np.copy(), mask_np.copy()

    def _rnd(self, min_value, max_value):
        return (max_value - min_value) * numpy.random.rand() + min_value

    def _mask_postprocessing(self, image):
        image = image.resize((self.width, self.height), Image.NEAREST)
        image = image.convert("L")

        for i in range(len(self.classes_ids)):
            image.putpixel((4 * i + self.width // 2, 4 * i + self.height // 2), self.classes_ids[i])

        image = image.quantize(self.classes_count)

        return image

