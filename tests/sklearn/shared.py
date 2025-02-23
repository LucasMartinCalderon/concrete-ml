"""Common functions or lists for test files, which can't be put in fixtures."""
from functools import partial

import numpy
import pytest
from torch import nn

from concrete.ml.sklearn import (
    DecisionTreeClassifier,
    GammaRegressor,
    LinearRegression,
    LinearSVC,
    LinearSVR,
    LogisticRegression,
    NeuralNetClassifier,
    NeuralNetRegressor,
    PoissonRegressor,
    RandomForestClassifier,
    TweedieRegressor,
    XGBClassifier,
)

regressor_models = [
    GammaRegressor,
    LinearRegression,
    LinearSVR,
    PoissonRegressor,
    TweedieRegressor,
    partial(
        NeuralNetRegressor,
        module__n_layers=3,
        module__n_w_bits=2,
        module__n_a_bits=2,
        module__n_accum_bits=7,  # Let's stay with 7 bits for test exec time
        module__n_hidden_neurons_multiplier=1,
        module__n_outputs=1,
        module__input_dim=20,
        module__activation_function=nn.SELU,
        max_epochs=10,
        verbose=0,
    ),
]

classifier_models = [
    DecisionTreeClassifier,
    RandomForestClassifier,
    XGBClassifier,
    LinearSVC,
    LogisticRegression,
    partial(
        NeuralNetClassifier,
        module__n_layers=3,
        module__n_w_bits=2,
        module__n_a_bits=2,
        module__n_accum_bits=7,  # Let's stay with 7 bits for test exec time.
        module__n_outputs=2,
        module__input_dim=20,
        module__activation_function=nn.SELU,
        max_epochs=10,
        verbose=0,
    ),
]

# Remark that NeuralNetClassifier is not here because it is particular model for us, needs much more
# parameters
classifiers = [
    pytest.param(
        model,
        {
            "dataset": "classification",
            "n_samples": 1000,
            "n_features": 10,
            "n_classes": 2,  # qnns do not have multiclass yet
            "n_informative": 10,
            "n_redundant": 0,
            "random_state": numpy.random.randint(0, 2**15),
        },
        id=model.__name__ if not isinstance(model, partial) else None,
    )
    for model in classifier_models
]

# Only LinearRegression supports multi targets
# GammaRegressor, PoissonRegressor and TweedieRegressor only handle positive target values
regressors = [
    pytest.param(
        model,
        {
            "dataset": "regression",
            "strictly_positive": model in [GammaRegressor, PoissonRegressor, TweedieRegressor],
            "n_samples": 200,
            "n_features": 10,
            "n_informative": 10,
            "n_targets": 2 if model == LinearRegression else 1,
            "noise": 0,
            "random_state": numpy.random.randint(0, 2**15),
        },
        id=model.__name__ if not isinstance(model, partial) else None,
    )
    for model in regressor_models
]
