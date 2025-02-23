"""Test Neural Networks compilations"""
import numpy
import onnx
import pytest
import torch
from concrete.numpy import MAXIMUM_BIT_WIDTH
from onnx import helper, numpy_helper
from torch import nn

from concrete.ml.onnx.convert import OPSET_VERSION_FOR_ONNX_EXPORT
from concrete.ml.quantization import QuantizedGemm
from concrete.ml.quantization.post_training import PostTrainingAffineQuantization
from concrete.ml.torch.numpy_module import NumpyModule

# INPUT_OUTPUT_FEATURE is the number of input and output of each of the network layers.
# (as well as the input of the network itself)
# Currently, with MAXIMUM_BIT_WIDTH bits maximum, we can use few weights
# max in the theoretical case.
INPUT_OUTPUT_FEATURE = [1, 2, 3]


class FC(nn.Module):
    """Torch model for the tests"""

    def __init__(self, input_output, act):
        super().__init__()
        self.fc1 = nn.Linear(in_features=input_output, out_features=input_output)
        self.act = act()
        self.fc2 = nn.Linear(in_features=input_output, out_features=input_output)

    def forward(self, x):
        """Forward pass."""
        out = self.fc1(x)
        out = self.act(out)
        out = self.fc2(out)

        return out


class FCSeq(nn.Module):
    """Torch model that should generate MatMul->Add ONNX patterns

    This network generates additions with a constant scalar
    """

    def __init__(self, input_output, act):
        super().__init__()
        self.feat = nn.Sequential()
        in_features = input_output
        self.n_layers = 2
        self.biases = [torch.Tensor(size=(1,)) for _ in range(self.n_layers)]
        for b in self.biases:
            nn.init.uniform_(b)

        for idx in range(self.n_layers):
            out_features = in_features if idx == self.n_layers - 1 else in_features
            layer_name = f"fc{idx}"
            layer = nn.Linear(in_features=in_features, out_features=out_features, bias=False)
            self.feat.add_module(layer_name, layer)
            in_features = out_features

        self.act = act()

    def forward(self, x):
        """Forward pass."""
        for idx, l in enumerate(self.feat):
            x = self.act(l(x) + self.biases[idx])
        return x


class FCSeqAddBiasVec(nn.Module):
    """Torch model that should generate MatMul->Add ONNX patterns

    This network tests the addition with a constant vector
    """

    def __init__(self, input_output, act):
        super().__init__()
        self.feat = nn.Sequential()
        in_features = input_output
        self.n_layers = 2
        self.biases = [torch.Tensor(size=(input_output,)) for _ in range(self.n_layers)]
        for b in self.biases:
            nn.init.uniform_(b)

        for idx in range(self.n_layers):
            out_features = in_features if idx == self.n_layers - 1 else in_features
            layer_name = f"fc{idx}"
            layer = nn.Linear(in_features=in_features, out_features=out_features, bias=False)
            self.feat.add_module(layer_name, layer)
            in_features = out_features

        self.act = act()

    def forward(self, x):
        """Forward pass."""
        for idx, l in enumerate(self.feat):
            x = self.act(l(x) + self.biases[idx])
        return x


class TinyCNN(nn.Module):
    """A very small CNN."""

    def __init__(self, n_classes, act) -> None:
        """Create the tiny CNN with two conv layers."""
        super().__init__()

        self.conv1 = nn.Conv2d(1, 2, 2, stride=1, padding=0)
        self.avg_pool1 = nn.AvgPool2d(2, 2)
        self.conv2 = nn.Conv2d(2, n_classes, 2, stride=1, padding=0)
        self.act = act()
        self.n_classes = n_classes

    def forward(self, x):
        """Forward the two layers with the chosen activation function"""
        x = self.act(self.avg_pool1(self.conv1(x)))
        x = self.act(self.conv2(x))
        return x


@pytest.mark.parametrize(
    "model",
    [pytest.param(FC), pytest.param(FCSeq), pytest.param(FCSeqAddBiasVec)],
)
@pytest.mark.parametrize(
    "input_output_feature",
    [pytest.param(input_output_feature) for input_output_feature in INPUT_OUTPUT_FEATURE],
)
@pytest.mark.parametrize(
    "activation",
    [
        nn.ReLU6,
        nn.Sigmoid,
    ],
)
@pytest.mark.parametrize("n_bits", [2, 9, 16])
@pytest.mark.parametrize("use_virtual_lib", [True, False])
def test_quantized_module_compilation(
    input_output_feature,
    model,
    activation,
    default_configuration,
    check_is_good_execution,
    n_bits,
    use_virtual_lib,
    is_vl_only_option,
):
    """Test a neural network compilation for FHE inference."""
    if not use_virtual_lib and is_vl_only_option:
        print("Warning, skipping non VL tests")
        return

    # Do not test unsupported bit widths when we are not using the Virtual Lib
    if not use_virtual_lib and n_bits > MAXIMUM_BIT_WIDTH:
        return

    # Define an input shape (n_examples, n_features)
    input_shape = (5, input_output_feature)

    # Build a random Quantized Fully Connected Neural Network

    # Define the torch model
    torch_fc_model = model(input_output_feature, activation)

    # Create random input
    numpy_input = numpy.random.uniform(-100, 100, size=input_shape)

    # Create corresponding numpy model
    numpy_fc_model = NumpyModule(torch_fc_model, torch.from_numpy(numpy_input).float())

    # Quantize with post-training static method
    post_training_quant = PostTrainingAffineQuantization(n_bits, numpy_fc_model)
    quantized_model = post_training_quant.quantize_module(numpy_input)

    # Quantize input
    q_input = quantized_model.quantize_input(numpy_input)

    # Compile
    quantized_model.compile(
        q_input,
        default_configuration,
        use_virtual_lib=use_virtual_lib,
    )

    for x_q in q_input:
        x_q = numpy.expand_dims(x_q, 0)
        check_is_good_execution(
            fhe_circuit=quantized_model.forward_fhe,
            function=quantized_model.forward,
            args=[x_q.astype(numpy.uint8)],
            check_function=numpy.array_equal,
            verbose=False,
        )


@pytest.mark.parametrize(
    "model",
    [pytest.param(TinyCNN)],
)
@pytest.mark.parametrize(
    "input_output_feature",
    [pytest.param(input_output_feature) for input_output_feature in [((8, 8), 2)]],
)
@pytest.mark.parametrize(
    "activation",
    [
        nn.ReLU6,
    ],
)
@pytest.mark.parametrize("use_virtual_lib", [True, False])
def test_quantized_cnn_compilation(
    input_output_feature,
    model,
    activation,
    default_configuration,
    check_is_good_execution,
    use_virtual_lib,
    is_vl_only_option,
):
    """Test a convolutional neural network compilation for FHE inference."""
    if not use_virtual_lib and is_vl_only_option:
        print("Warning, skipping non VL tests")
        return

    n_bits = 2

    # Define an input shape (n_examples, n_features)
    input_shape, n_classes = input_output_feature

    # Build a randomly initialized Quantized CNN Network

    # Define the torch model
    torch_cnn_model = model(n_classes, activation)
    # Create random inputs with 1 channel each
    numpy_input = numpy.random.uniform(-1, 1, size=(1, 1, *input_shape))
    tensor_input = torch.from_numpy(numpy_input).float()

    # Create corresponding numpy model
    torch_cnn_model = NumpyModule(torch_cnn_model, tensor_input)
    # Quantize with post-training static method
    post_training_quant = PostTrainingAffineQuantization(n_bits, torch_cnn_model)
    quantized_model = post_training_quant.quantize_module(numpy_input)

    # Quantize input
    q_input = quantized_model.quantize_input(numpy_input)

    # Compile
    quantized_model.compile(
        q_input,
        default_configuration,
        use_virtual_lib=use_virtual_lib,
    )

    for x_q in q_input:
        x_q = numpy.expand_dims(x_q, 0)
        check_is_good_execution(
            fhe_circuit=quantized_model.forward_fhe,
            function=quantized_model.forward,
            args=[x_q.astype(numpy.uint8)],
            check_function=numpy.array_equal,
            verbose=False,
        )


class NumpyModuleTest(NumpyModule):
    """Test class to build NumpyModule in an alternative way."""

    def __init__(self, onnx_model: onnx.ModelProto):  # pylint: disable=super-init-not-called
        self.numpy_forward = lambda x: x
        self._onnx_model = onnx_model


def test_post_training_quantization_constant_folding():
    """Test to check that constant folding works properly."""

    # First add a few initializers
    f_one = 1.0
    f_zero = 0.0

    f_ones_init = numpy_helper.from_array(numpy.ones((10, 10), dtype=numpy.float32), "f_ones")
    f_zeros_init = numpy_helper.from_array(numpy.zeros((10, 10), dtype=numpy.float32), "f_zeros")

    constant_f_one = helper.make_node(
        "Constant",
        inputs=[],
        outputs=["constant_f_one"],
        name="constant_f_one_node",
        **{"value_float": f_one},
    )
    constant_f_zero = helper.make_node(
        "Constant",
        inputs=[],
        outputs=["constant_f_zero"],
        name="constant_f_zero_node",
        **{"value_float": f_zero},
    )

    add_one_and_zero = helper.make_node(
        "Add",
        inputs=["constant_f_one", "constant_f_zero"],
        outputs=["add_one_and_zero"],
        name="add_one_and_zero_node",
    )

    sub_zeros_and_ones = helper.make_node(
        "Sub",
        inputs=["f_zeros", "f_ones"],
        outputs=["sub_zeros_and_ones"],
        name="sub_zeros_and_ones_node",
    )

    model_input_name = "x_input"
    x_input = helper.make_tensor_value_info(model_input_name, onnx.TensorProto.FLOAT, [10, 10])
    model_output_name = "y_output"
    y_output = helper.make_tensor_value_info(model_output_name, onnx.TensorProto.FLOAT, [10, 10])

    add_input_f_one = helper.make_node(
        "Add",
        inputs=["constant_f_zero", "constant_f_one"],
        outputs=["input_plus_one"],
        name="input_plus_one_node",
    )

    exp_f_zero = helper.make_node(
        "Exp",
        inputs=["constant_f_zero"],
        outputs=["exp_f_zero"],
        name="exp_f_zero_node",
    )

    add_input_f_one_exp = helper.make_node(
        "Add",
        inputs=["input_plus_one", "exp_f_zero"],
        outputs=["input_plus_two"],
        name="input_plus_two_node",
    )

    negative_input = helper.make_node(
        "Mul",
        inputs=["input_plus_two", "sub_zeros_and_ones"],
        outputs=["negative_input"],
        name="negative_input_node",
    )

    negative_input_plus_one = helper.make_node(
        "Add",
        inputs=["negative_input", "add_one_and_zero"],
        outputs=["negative_input_plus_one"],
        name="negative_input_plus_one_node",
    )

    gemm = helper.make_node(
        "Gemm",
        inputs=["x_input", "negative_input_plus_one"],
        outputs=[model_output_name],
        name="matmul_with_folded_cst",
        **{"transA": 0, "transB": 0, "alpha": 1.0, "beta": 1.0},
    )

    graph_def = helper.make_graph(
        nodes=[
            constant_f_one,
            constant_f_zero,
            add_one_and_zero,
            sub_zeros_and_ones,
            add_input_f_one,
            exp_f_zero,
            add_input_f_one_exp,
            negative_input,
            negative_input_plus_one,
            gemm,
        ],
        name="test_constant_folding",
        inputs=[x_input],
        outputs=[y_output],
        initializer=[f_ones_init, f_zeros_init],
    )

    # Create the model (ModelProto)
    model_def = helper.make_model(graph_def, producer_name="onnx-example")
    model_def.opset_import[0].version = OPSET_VERSION_FOR_ONNX_EXPORT

    model_def = onnx.shape_inference.infer_shapes(model_def)

    onnx.checker.check_model(model_def)

    numpy_model = NumpyModuleTest(model_def)

    # Quantize with post-training static method
    post_training_quant = PostTrainingAffineQuantization(
        MAXIMUM_BIT_WIDTH, numpy_model, is_signed=True
    )

    numpy_input = numpy.random.random(size=(10, 10))

    post_training_quant.quantize_module(numpy_input)

    expected_constant = (0.0 + 1.0) + (
        (numpy.zeros((10, 10), dtype=numpy.float32) - numpy.ones((10, 10), dtype=numpy.float32))
        * ((1.0 + 0.0) + numpy.exp(0.0))
    )

    # Check we have only the gemm node in the quant_ops_dict after quantization as it's the only one
    # that depends on a variable input
    assert len(post_training_quant.quant_ops_dict) == 1
    assert model_output_name in post_training_quant.quant_ops_dict
    assert isinstance(
        q_gemm := post_training_quant.quant_ops_dict[model_output_name][1], QuantizedGemm
    )
    assert numpy.array_equal(q_gemm.constant_inputs[1].values, expected_constant)
