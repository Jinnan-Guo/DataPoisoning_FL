import os
import numpy as np
from loguru import logger
from federated_learning.arguments import Arguments
from federated_learning.dimensionality_reduction import calculate_pca_of_gradients
from federated_learning.parameters import get_layer_parameters
from federated_learning.parameters import calculate_parameter_gradients
from federated_learning.utils import get_model_files_for_epoch
from federated_learning.utils import get_model_files_for_suffix
from federated_learning.utils import apply_standard_scaler
from federated_learning.utils import get_worker_num_from_model_file_name
from client import Client
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from sklearn.cluster import KMeans

# Paths you need to put in.
MODELS_PATH = f"{os.getcwd()}/3001_models"

# The epochs over which you are calculating gradients.
EPOCHS = list(range(3, 10))

# The layer of the NNs that you want to investigate.
#   If you are using the provided Fashion MNIST CNN, this should be "fc.weight"
#   If you are using the provided Cifar 10 CNN, this should be "fc2.weight"
LAYER_NAME = "fc2.weight"

# The source class.
CLASS_NUM = 1

# The IDs for the poisoned workers. This needs to be manually filled out.
# You can find this information at the beginning of an experiment's log file.
POISONED_WORKER_IDS = []

# The resulting graph is saved to a file
SAVE_NAME = "defense_results.jpg"
SAVE_NAME_CLUSTER = "defense_cluster.jpg"
SAVE_SIZE = (18, 14)

SIZE_THRESHOLD = 0.3 # outlier should be <= 30%

DISTANCE_THRESHOLD = 12 # distance should more than 12

def load_models(args, model_filenames):
    clients = []
    for model_filename in model_filenames:
        client = Client(args, 0, None, None)
        client.set_net(client.load_model_from_file(model_filename))

        clients.append(client)

    return clients


def plot_gradients_2d(gradients):
    fig = plt.figure()

    for (worker_id, gradient) in gradients:
        if worker_id in POISONED_WORKER_IDS:
            # print data point
            # print(f"poisoned data point {gradient}")
            plt.scatter(gradient[0], gradient[1], color="blue", marker="x", s=1000, linewidth=5)
        else:
            plt.scatter(gradient[0], gradient[1], color="orange", s=180)

    fig.set_size_inches(SAVE_SIZE, forward=False)
    plt.grid(False)
    plt.margins(0,0)
    plt.savefig(SAVE_NAME, bbox_inches='tight', pad_inches=0.1)

def plot_gradients_with_label(gradients, outlier_label):
    fig = plt.figure()

    for (cluster_label, gradient) in gradients:
        if cluster_label == outlier_label:
            # print data point
            # print(f"poisoned data point {gradient}")
            plt.scatter(gradient[0], gradient[1], color="blue", marker="x", s=1000, linewidth=5)
        else:
            plt.scatter(gradient[0], gradient[1], color="orange", s=180)

    fig.set_size_inches(SAVE_SIZE, forward=False)
    plt.grid(False)
    plt.margins(0,0)
    plt.savefig(SAVE_NAME_CLUSTER, bbox_inches='tight', pad_inches=0.1)   
    

if __name__ == '__main__':
    args = Arguments(logger)
    args.log()

    model_files = sorted(os.listdir(MODELS_PATH))
    logger.debug("Number of models: {}", str(len(model_files)))

    param_diff = []
    worker_ids = []

    for epoch in EPOCHS:
        start_model_files = get_model_files_for_epoch(model_files, epoch)
        start_model_file = get_model_files_for_suffix(start_model_files, args.get_epoch_save_start_suffix())[0]
        start_model_file = os.path.join(MODELS_PATH, start_model_file)
        start_model = load_models(args, [start_model_file])[0]

        start_model_layer_param = list(get_layer_parameters(start_model.get_nn_parameters_cpu(), LAYER_NAME)[CLASS_NUM])

        end_model_files = get_model_files_for_epoch(model_files, epoch)
        end_model_files = get_model_files_for_suffix(end_model_files, args.get_epoch_save_end_suffix())

        for end_model_file in end_model_files:
            worker_id = get_worker_num_from_model_file_name(end_model_file)
            end_model_file = os.path.join(MODELS_PATH, end_model_file)
            end_model = load_models(args, [end_model_file])[0]

            end_model_layer_param = list(get_layer_parameters(end_model.get_nn_parameters_cpu(), LAYER_NAME)[CLASS_NUM])

            gradient = calculate_parameter_gradients(logger, start_model_layer_param, end_model_layer_param)
            gradient = gradient.flatten()

            param_diff.append(gradient)
            worker_ids.append(worker_id)

    logger.info("Gradients shape: ({}, {})".format(len(param_diff), param_diff[0].shape[0]))

    logger.info("Prescaled gradients: {}".format(str(param_diff)))
    scaled_param_diff = apply_standard_scaler(param_diff)
    logger.info("Postscaled gradients: {}".format(str(scaled_param_diff)))
    dim_reduced_gradients = calculate_pca_of_gradients(logger, scaled_param_diff, 2)
    logger.info("PCA reduced gradients: {}".format(str(dim_reduced_gradients)))

    logger.info("Dimensionally-reduced gradients shape: ({}, {})".format(len(dim_reduced_gradients), dim_reduced_gradients[0].shape[0]))

    plot_gradients_2d(zip(worker_ids, dim_reduced_gradients))

    # clustering
    kmeans = KMeans(2)
    cluster_labels = kmeans.fit_predict(dim_reduced_gradients)
    print(f"cluster labels {cluster_labels}")
    outlier_label = np.argmin(np.bincount(cluster_labels))

    outlier_ratio = np.bincount(cluster_labels)[outlier_label] / np.bincount(cluster_labels).sum()
    print(f"Outlier ratio {outlier_ratio}")
    centroids = kmeans.cluster_centers_
    distance = np.linalg.norm(centroids[0] - centroids[1])
    print(f"Center distance {distance}")

    if outlier_ratio > SIZE_THRESHOLD or distance < DISTANCE_THRESHOLD:
        print(f"No outlier detected")
    else:
        plot_gradients_with_label(zip(cluster_labels, dim_reduced_gradients), outlier_label)
