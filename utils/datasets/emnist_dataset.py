# Copyright 2019, Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Library for loading and preprocessing EMNIST training and testing data."""

import collections
from typing import List, Optional, Tuple

import numpy as np
import tensorflow as tf
import tensorflow_federated as tff

MAX_CLIENT_DATASET_SIZE = 418
NUM_CLIENTS_P13N_TRAIN = 2500


def _reshape_for_digit_recognition(element):
  return (tf.expand_dims(element['pixels'], axis=-1), element['label'])


def _reshape_for_autoencoder(element):
  x = 1 - tf.reshape(element['pixels'], (-1, 28 * 28))
  return (x, x)


def create_preprocess_fn(
    num_epochs: int,
    batch_size: int,
    max_batches: int = -1,
    shuffle_buffer_size: int = MAX_CLIENT_DATASET_SIZE,
    emnist_task: str = 'digit_recognition',
    num_parallel_calls: tf.Tensor = tf.data.experimental.AUTOTUNE
) -> tff.Computation:
  """Creates a preprocessing function for EMNIST client datasets.

  The preprocessing shuffles, repeats, batches, and then reshapes, using
  the `shuffle`, `repeat`, `batch`, and `map` attributes of a
  `tf.data.Dataset`, in that order.

  Args:
    num_epochs: An integer representing the number of epochs to repeat the
      client datasets.
    batch_size: An integer representing the batch size on clients.
    max_batches: An integer representing the limit on the number of batches.
    shuffle_buffer_size: An integer representing the shuffle buffer size on
      clients. If set to a number <= 1, no shuffling occurs.
    emnist_task: A string indicating the EMNIST task being performed. Must be
      one of 'digit_recognition' or 'autoencoder'. If the former, then elements
      are mapped to tuples of the form (pixels, label), if the latter then
      elements are mapped to tuples of the form (pixels, pixels).
    num_parallel_calls: An integer representing the number of parallel calls
      used when performing `tf.data.Dataset.map`.

  Returns:
    A `tff.Computation` performing the preprocessing discussed above.
  """
  if num_epochs < 0 and max_batches < 0:
    raise ValueError(f'Either num_epochs ({num_epochs}) or max_batches '
                     f'({max_batches}) must be a positive integer.')
  if shuffle_buffer_size <= 1:
    shuffle_buffer_size = 1

  if emnist_task == 'digit_recognition':
    mapping_fn = _reshape_for_digit_recognition
  elif emnist_task == 'autoencoder':
    mapping_fn = _reshape_for_autoencoder
  else:
    raise ValueError('emnist_task must be one of "digit_recognition" or '
                     '"autoencoder".')

  # Features are intentionally sorted lexicographically by key for consistency
  # across datasets.
  feature_dtypes = collections.OrderedDict(
      label=tff.TensorType(tf.int32),
      pixels=tff.TensorType(tf.float32, shape=(28, 28)))

  @tff.tf_computation(tff.SequenceType(feature_dtypes))
  def preprocess_fn(dataset):
    return dataset.shuffle(shuffle_buffer_size).repeat(num_epochs).batch(
        batch_size, drop_remainder=False).take(max_batches).map(
            mapping_fn, num_parallel_calls=num_parallel_calls)

  return preprocess_fn


def get_federated_datasets(
    train_client_batch_size: int = 20,
    test_client_batch_size: int = 100,
    train_client_epochs_per_round: int = 1,
    test_client_epochs_per_round: int = 1,
    train_shuffle_buffer_size: int = MAX_CLIENT_DATASET_SIZE,
    test_shuffle_buffer_size: int = 1,
    only_digits: bool = False,
    emnist_task: str = 'digit_recognition'
) -> Tuple[tff.simulation.datasets.ClientData,
           tff.simulation.datasets.ClientData]:
  """Loads and preprocesses federated EMNIST training and testing sets.

  Args:
    train_client_batch_size: The batch size for all train clients.
    test_client_batch_size: The batch size for all test clients.
    train_client_epochs_per_round: The number of epochs each train client should
      iterate over their local dataset, via `tf.data.Dataset.repeat`. Must be
      set to a positive integer.
    test_client_epochs_per_round: The number of epochs each test client should
      iterate over their local dataset, via `tf.data.Dataset.repeat`. Must be
      set to a positive integer.
    train_shuffle_buffer_size: An integer representing the shuffle buffer size
      (as in `tf.data.Dataset.shuffle`) for each train client's dataset. By
      default, this is set to the largest dataset size among all clients. If set
      to some integer less than or equal to 1, no shuffling occurs.
    test_shuffle_buffer_size: An integer representing the shuffle buffer size
      (as in `tf.data.Dataset.shuffle`) for each test client's dataset. If set
      to some integer less than or equal to 1, no shuffling occurs.
    only_digits: A boolean representing whether to take the digits-only
      EMNIST-10 (with only 10 labels) or the full EMNIST-62 dataset with digits
      and characters (62 labels). If set to True, we use EMNIST-10, otherwise we
      use EMNIST-62.
    emnist_task: A string indicating the EMNIST task being performed. Must be
      one of 'digit_recognition' or 'autoencoder'. If the former, then elements
      are mapped to tuples of the form (pixels, label), if the latter then
      elements are mapped to tuples of the form (pixels, pixels).

  Returns:
    A tuple (emnist_train, emnist_test) of `tff.simulation.datasets.ClientData`
    instances representing the federated training and test datasets.
  """

  if train_client_epochs_per_round < 1:
    raise ValueError(
        'train_client_epochs_per_round must be a positive integer.')
  if test_client_epochs_per_round < 0:
    raise ValueError('test_client_epochs_per_round must be a positive integer.')
  if train_shuffle_buffer_size <= 1:
    train_shuffle_buffer_size = 1
  if test_shuffle_buffer_size <= 1:
    test_shuffle_buffer_size = 1

  emnist_train, emnist_test = tff.simulation.datasets.emnist.load_data(
      only_digits=only_digits)

  train_preprocess_fn = create_preprocess_fn(
      num_epochs=train_client_epochs_per_round,
      batch_size=train_client_batch_size,
      shuffle_buffer_size=train_shuffle_buffer_size,
      emnist_task=emnist_task)

  test_preprocess_fn = create_preprocess_fn(
      num_epochs=test_client_epochs_per_round,
      batch_size=test_client_batch_size,
      shuffle_buffer_size=test_shuffle_buffer_size,
      emnist_task=emnist_task)

  emnist_train = emnist_train.preprocess(train_preprocess_fn)
  emnist_test = emnist_test.preprocess(test_preprocess_fn)
  return emnist_train, emnist_test


def get_centralized_datasets(
    train_batch_size: int = 20,
    test_batch_size: int = 500,
    train_shuffle_buffer_size: int = 10000,
    test_shuffle_buffer_size: int = 1,
    only_digits: bool = False,
    emnist_task: str = 'digit_recognition'
) -> Tuple[tf.data.Dataset, tf.data.Dataset]:
  """Loads and preprocesses centralized EMNIST training and testing sets.

  Args:
    train_batch_size: The batch size for the training dataset.
    test_batch_size: The batch size for the test dataset.
    train_shuffle_buffer_size: An integer specifying the buffer size used to
      shuffle the train dataset via `tf.data.Dataset.shuffle`. If set to an
      integer less than or equal to 1, no shuffling occurs.
    test_shuffle_buffer_size: An integer specifying the buffer size used to
      shuffle the test dataset via `tf.data.Dataset.shuffle`. If set to an
      integer less than or equal to 1, no shuffling occurs.
    only_digits: A boolean representing whether to take the digits-only
      EMNIST-10 (with only 10 labels) or the full EMNIST-62 dataset with digits
      and characters (62 labels). If set to True, we use EMNIST-10, otherwise we
      use EMNIST-62.
    emnist_task: A string indicating the EMNIST task being performed. Must be
      one of 'digit_recognition' or 'autoencoder'. If the former, then elements
      are mapped to tuples of the form (pixels, label), if the latter then
      elements are mapped to tuples of the form (pixels, pixels).

  Returns:
    A tuple (train_dataset, test_dataset) of `tf.data.Dataset` instances
    representing the centralized training and test datasets.
  """
  if train_shuffle_buffer_size <= 1:
    train_shuffle_buffer_size = 1
  if test_shuffle_buffer_size <= 1:
    test_shuffle_buffer_size = 1

  emnist_train, emnist_test = tff.simulation.datasets.emnist.load_data(
      only_digits=only_digits)

  emnist_train = emnist_train.create_tf_dataset_from_all_clients()
  emnist_test = emnist_test.create_tf_dataset_from_all_clients()

  train_preprocess_fn = create_preprocess_fn(
      num_epochs=1,
      batch_size=train_batch_size,
      shuffle_buffer_size=train_shuffle_buffer_size,
      emnist_task=emnist_task)

  test_preprocess_fn = create_preprocess_fn(
      num_epochs=1,
      batch_size=test_batch_size,
      shuffle_buffer_size=test_shuffle_buffer_size,
      emnist_task=emnist_task)

  emnist_train = train_preprocess_fn(emnist_train)
  emnist_test = test_preprocess_fn(emnist_test)

  return emnist_train, emnist_test


def get_federated_p13n_datasets(
    train_batch_size: int = 20,
    train_epochs: int = 1,
    train_max_batches: int = -1,
    eval_batch_size: int = 20,
    eval_inner_epochs: int = 1,
    eval_inner_max_batches: int = -1,
    only_digits: bool = False,
    emnist_task: str = 'digit_recognition',
    shuffle_buffer_size: int = MAX_CLIENT_DATASET_SIZE,
    seed: Optional[int] = None
) -> Tuple[List[str], List[str], tff.Computation, tff.Computation]:
  """Loads and preprocesses federated EMNIST p13n training and testing sets.

  Args:
    train_batch_size: The batch size of the training dataset.
    train_epochs: The number of epochs to repeat the training dataset.
    train_max_batches: The number of batches to limit the training dataset to.
    eval_batch_size: The batch size of the evaluation dataset.
    eval_inner_epochs: An integer representing the number of inner loop epochs
      at evaluation time.
    eval_inner_max_batches: An integer representing the limit on the number of
      batches used in the inner loop.
    only_digits: A boolean representing whether to take the digits-only
      EMNIST-10 (with only 10 labels) or the full EMNIST-62 dataset with digits
      and characters (62 labels). If set to True, we use EMNIST-10, otherwise we
      use EMNIST-62.
    emnist_task: A string indicating the EMNIST task being performed. Must be
      one of 'digit_recognition' or 'autoencoder'. If the former, then elements
      are mapped to tuples of the form (pixels, label), if the latter then
      elements are mapped to tuples of the form (pixels, pixels).
    shuffle_buffer_size: An integer representing the shuffle buffer size
      (as in `tf.data.Dataset.shuffle`) for each train client's dataset. By
      default, this is set to the largest dataset size among all clients. If set
      to some integer less than or equal to 1, no shuffling occurs.
    seed: An optional integer for seeding random splitting of the clients into
      training and test sets.

  Returns:
    A dict that contains train and test client ids, dataset computation used
    for federated training and a list of test client datasets.
  """

  emnist_train, emnist_test = tff.simulation.datasets.emnist.load_data(
    only_digits=only_digits)
  client_ids = emnist_train.client_ids
  assert set(client_ids) == set(emnist_test.client_ids)

  train_preprocess_fn = create_preprocess_fn(
    num_epochs=train_epochs,
    max_batches=train_max_batches,
    batch_size=train_batch_size,
    shuffle_buffer_size=shuffle_buffer_size,
    emnist_task=emnist_task)

  eval_inner_preprocess_fn = create_preprocess_fn(
    num_epochs=eval_inner_epochs,
    max_batches=eval_inner_max_batches,
    batch_size=eval_batch_size,
    # Note: we still need to shuffle data for fine-tuning at eval time.
    shuffle_buffer_size=shuffle_buffer_size,
    emnist_task=emnist_task)

  eval_outer_preprocess_fn = create_preprocess_fn(
    num_epochs=1,  # One epoch is always sufficient for eval.
    batch_size=eval_batch_size,
    shuffle_buffer_size=1,
    emnist_task=emnist_task)

  # Split clients into training and test sets.
  rng = np.random.RandomState(seed=seed)
  client_ids = list(rng.permutation(client_ids))
  client_ids_train = client_ids[:NUM_CLIENTS_P13N_TRAIN]
  client_ids_test = client_ids[NUM_CLIENTS_P13N_TRAIN:]

  @tff.tf_computation(tf.string)
  def build_train_dataset_from_client_id(client_id):
    # Explicit placement on the CPU avoids a known TF issue:
    # https://github.com/tensorflow/tensorflow/issues/34112.
    # with tf.device('/CPU:0'):
    client_dataset_train = emnist_train.dataset_computation(client_id)
    client_dataset_test = emnist_test.dataset_computation(client_id)
    client_dataset_full = client_dataset_train.concatenate(client_dataset_test)
    return train_preprocess_fn(client_dataset_full)

  @tff.tf_computation(tf.string)
  def build_eval_dataset_from_client_id(client_id):
    client_dataset_train = emnist_train.dataset_computation(client_id)
    client_dataset_test = emnist_test.dataset_computation(client_id)
    return collections.OrderedDict([
      ('train_data', eval_inner_preprocess_fn(client_dataset_train)),
      ('test_data', eval_outer_preprocess_fn(client_dataset_test)),
    ])

  return (client_ids_train, client_ids_test,
          build_train_dataset_from_client_id, build_eval_dataset_from_client_id)
