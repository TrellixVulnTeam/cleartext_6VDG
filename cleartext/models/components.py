from typing import Tuple

import torch
from torch import nn as nn, Tensor
from torch.nn.functional import softmax

from .. import utils


class Encoder(nn.Module):
    """Encoder module.

    The encoder represents its inputs using fixed, pre-trained GloVe embeddings, which are passed through a
    bidirectional LSTM.

    Attributes
    ----------
    units: int
        Number of hidden units in the LSTM.
    embed_dim: int
        Embedding dimensionality.
    embedding: Module
        Embedding module.
    lstm: Module
        Bidirectional LSTM module.
    """

    def __init__(self, embed_weights: Tensor, units: int, enc_layers: int, dropout: float) -> None:
        """Initialize the encoder.

        Constructs encoder sub-modules and initializes their weights using `utils.init_weights`.

        :param embed_weights: Tensor
            Embedding weights of shape (src_vocab_size, embed_dim).
        :param units: int
            Number of LSTM hidden units.
        :param enc_layers: int
            Number of layers.
        """
        super().__init__()
        self.units = units
        self.embed_dim = embed_weights.shape[1]

        self.embedding = nn.Embedding.from_pretrained(embed_weights)
        self.dropout = nn.Dropout(dropout)
        self.lstm = nn.LSTM(self.embed_dim, units, num_layers=enc_layers, dropout=dropout, bidirectional=True)

        utils.init_weights_(self.lstm)

    def forward(self, source: Tensor) -> Tuple[Tensor, Tuple[Tensor, Tensor]]:
        """Encoder a source sequence by forward propagation.

        :param source: Tensor
            Source sequence of shape (seq_len, batch_size).
        :return: Tuple[Tensor, Tensor, Tensor]
            Outputs of shape (seq_len, batch_size, 2 * units) and tuple containing hidden/cell states, respectively,
            both of shape (2 * enc_layers, batch_size, units).
        """
        embedded = self.embedding(source)
        embedded = self.dropout(embedded)
        outputs, state = self.lstm(embedded, None)
        hidden, cell = state

        return outputs, (hidden, cell)


class Attention(nn.Module):
    """Attention module.

    Used to compute Bahdanau attention weights over encoder outputs.

    Attributes
    ----------
    attn_in: int
        Dimensionality of attention input.
    fc1: Module
        First fully-connected layer
    fc2: Module
        Second fully-connected layer.
    dropout: Module
        Dropout module
    """
    def __init__(self, enc_units: int, dec_units: int, attn_units: int, dropout: float = 0.2) -> None:
        """Initializes the attention module.

        :param enc_units: int
            Encoder output dimensionality.
        :param dec_units: int
            Decoder state dimensionality.
        :param attn_units: int
            Attention dimensionality.
        :param dropout: float
            Dropout probability.
        """
        super().__init__()
        self.attn_in = 2 * enc_units + dec_units

        self.fc1 = nn.Linear(self.attn_in, attn_units)
        self.fc2 = nn.Linear(attn_units, 1)
        self.dropout = nn.Dropout(dropout)

        utils.init_weights_(self.fc1)
        utils.init_weights_(self.fc2)

    def forward(self, dec_state: Tensor, enc_outputs: Tensor) -> Tensor:
        """Computes (Bahdanau) attention weights.

        :param dec_state: Tensor
            Previous decoder state (from top layer) of shape (batch_size, dec_units).
        :param enc_outputs: Tensor
            Encoder outputs of shape (source_len, batch_size, 2 * enc_units).
        :return:
            Attention weights of shape (batch_size, source_len).
        """
        source_len = enc_outputs.shape[0]

        # vectorize computation of Bahdanau attention scores for all encoder outputs
        dec_state = dec_state.unsqueeze(1).repeat(1, source_len, 1)
        enc_outputs = enc_outputs.permute(1, 0, 2)
        combined = torch.cat((dec_state, enc_outputs), dim=2)
        combined = self.dropout(combined)
        scores = torch.tanh(self.fc1(combined))
        scores = self.fc2(scores).squeeze(-1)

        weights = softmax(scores, dim=1)
        return weights


class Decoder(nn.Module):
    """Decoder module.

    Predicts next token probabilities using previous token and state and context vector.

    Attributes
    ----------
    vocab_size: int
        Target vocabulary size.
    embed_dim: int
        Embedding dimension.
    embedding: Module
        Embedding layer.
    lstm: Module
        LSTM.
    fc: Module
        Fully-connected layer that outputs scores over target vocabulary.
    dropout: Module
        Dropout module.
    """
    def __init__(self, embed_weights: Tensor, dec_units: int, enc_units: int, num_layers: int, dropout: float) -> None:
        """Initializes the decoder module.

        :param embed_weights: Tensor
            Embedding weights of shape (trg_vocab_size, embed_dim).
        :param dec_units: int
            Number of hidden units in LSTM decoder.
        :param enc_units: int
            Number of hidden units in LSTM encoder.
        :param num_layers: int
            Number of LSTM layers.
        :param dropout: float
            Dropout probability.
        """
        super().__init__()
        self.vocab_size, embed_dim = embed_weights.shape

        self.embedding = nn.Embedding.from_pretrained(embed_weights)
        self.lstm = nn.LSTM((enc_units * 2) + embed_dim, dec_units, num_layers=num_layers, dropout=dropout)
        self.fc = nn.Linear(dec_units + 2 * enc_units + embed_dim, self.vocab_size)
        self.dropout = nn.Dropout(dropout)

        utils.init_weights_(self.lstm)
        utils.init_weights_(self.fc)

    def forward(self, token: Tensor, context: Tensor, dec_hidden: Tensor, dec_cell: Tensor) \
            -> Tuple[Tensor, Tuple[Tensor, Tensor]]:
        """Decodes the next token.

        :param token: Tensor
            Numericalized token of shape (batch_size,).
        :param context:
            Context vector of shape (1, batch_size, 2 * enc_units).
        :param dec_hidden:
            Decoder hidden state of shape (num_layers, batch_size, dec_units).
        :param dec_cell:
            Decoder cell state of shape (num_layers, batch_size, dec_units).
        :return: Tuple[Tensor, Tensor]
            Vocabulary scores of shape (batch_size, vocab_size) and tuple containing decoder hidden and cell states,
            respectively, both of shape (num_layers, batch_size, dec_units).
        """
        token = token.unsqueeze(0)
        embedded = self.embedding(token)
        embedded = self.dropout(embedded)

        rnn_input = torch.cat((embedded, context), dim=2)
        output, (dec_hidden, dec_cell) = self.lstm(rnn_input, (dec_hidden, dec_cell))

        embedded = embedded.squeeze(0)
        output = output.squeeze(0)
        context = context.squeeze(0)

        # compute output using lstm output, context vector, and embedding of previous output
        combined = torch.cat((output, context, embedded), dim=1)
        combined = self.dropout(combined)
        output = self.fc(combined)

        # return logits (rather than softmax activations) for compatibility with cross-entropy loss
        return output, (dec_hidden, dec_cell)
