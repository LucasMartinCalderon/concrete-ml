"""Tests pipelines in our models."""
import warnings
from functools import partial

import numpy
import pytest
from concrete.numpy import MAXIMUM_BIT_WIDTH
from shared import classifiers, regressors
from sklearn.decomposition import PCA
from sklearn.exceptions import ConvergenceWarning
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn

from concrete.ml.sklearn import NeuralNetClassifier, NeuralNetRegressor


@pytest.mark.parametrize("model, parameters", classifiers + regressors)
def test_pipeline_classifiers_regressors(model, parameters, load_data):
    """Tests that classifiers and regressors work well within sklearn pipelines."""
    if isinstance(model, partial):
        # Tested in test_pipeline_and_cv_qnn
        if model.func in [NeuralNetClassifier, NeuralNetRegressor]:
            return

    x, y = load_data(**parameters)

    pipe_cv = Pipeline(
        [
            ("pca", PCA(n_components=2)),
            ("scaler", StandardScaler()),
            ("model", model()),
        ]
    )
    # Do a grid search to find the best hyperparameters
    param_grid = {
        "model__n_bits": [2, 3],
    }
    grid_search = GridSearchCV(pipe_cv, param_grid, error_score="raise", cv=3)

    # Sometimes, we miss convergence, which is not a problem for our test
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        grid_search.fit(x, y)


qnn = [
    (
        {
            "dataset": "classification",
            "n_samples": 1000,
            "n_features": 10,
            "n_redundant": 0,
            "n_repeated": 0,
            "n_informative": 5,
            "n_classes": 2,
            "class_sep": 2,
            "random_state": 42,
        }
    )
]


@pytest.mark.parametrize("parameters", qnn)
def test_pipeline_and_cv_qnn(parameters, load_data):
    """Test whether we can use the quantized NN sklearn wrappers in pipelines and in
    cross-validation"""

    x, y = load_data(**parameters)

    x = x.astype(numpy.float32)

    # Perform a classic test-train split (deterministic by fixing the seed)
    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.25,
        random_state=42,
    )
    params = {
        "module__n_layers": 3,
        "module__n_w_bits": 2,
        "module__n_a_bits": 2,
        "module__n_accum_bits": MAXIMUM_BIT_WIDTH,
        "module__n_outputs": 2,
        "module__input_dim": 2,
        "module__activation_function": nn.SELU,
        "max_epochs": 10,
        "verbose": 0,
    }

    pipe = Pipeline(
        [
            ("pca", PCA(n_components=2)),
            ("scaler", StandardScaler()),
            ("net", NeuralNetClassifier(**params)),
        ]
    )

    pipe.fit(x_train, y_train)
    pipe.score(x_test, y_test)

    pipe_cv = Pipeline(
        [
            ("pca", PCA(n_components=2)),
            ("scaler", StandardScaler()),
            ("net", NeuralNetClassifier(**params)),
        ]
    )

    clf = GridSearchCV(
        pipe_cv,
        {"net__module__n_layers": (3, 5), "net__module__activation_function": (nn.Tanh, nn.ReLU6)},
        error_score="raise",
    )
    clf.fit(x_train, y_train)
