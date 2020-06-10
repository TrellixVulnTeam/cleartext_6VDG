import random
from typing import Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor


class Encoder(nn.Module):
    def __init__(self, embed_weights: Tensor, units: int, dropout: float) -> None:
        super().__init__()
        self.embedding = nn.Embedding.from_pretrained(embed_weights)
        embed_dim = embed_weights.shape[1]
        self.gru = nn.GRU(embed_dim, units, bidirectional=True)
        self.fc = nn.Linear(units * 2, units)
        self.dropout = nn.Dropout(dropout)

    def forward(self, source: Tensor) -> Tuple[Tensor, Tensor]:
        embedded = self.embedding(source)
        # todo: ensure state properly initialized
        outputs, state = self.gru(embedded)

        # combine and reshape bidirectional states for compatibility with (unidirectional) decoder
        combined = torch.cat((state[-2, :, :], state[-1, :, :]), dim=1)
        combined = self.dropout(combined)
        state = torch.tanh(self.fc(combined))

        return outputs, state


class Attention(nn.Module):
    def __init__(self, state_dim: int, units: int, dropout: float = 0) -> None:
        super().__init__()
        self.attn_in = state_dim * 3
        self.fc = nn.Linear(self.attn_in, units)
        self.dropout = nn.Dropout(dropout)

    def forward(self, dec_state: Tensor, enc_outputs: Tensor) -> Tensor:
        source_len = enc_outputs.shape[0]

        # vectorize computation of Bahdanau attention scores for all encoder outputs
        dec_state = dec_state.unsqueeze(1).repeat(1, source_len, 1)
        enc_outputs = enc_outputs.permute(1, 0, 2)
        combined = torch.cat((dec_state, enc_outputs), dim=2)
        combined = self.dropout(combined)
        scores = torch.tanh(self.fc(combined))
        # todo: shouldn't this be fully connected?
        scores = torch.sum(scores, dim=2)

        weights = F.softmax(scores, dim=1)
        return weights


class Decoder(nn.Module):
    def __init__(self, embed_weights: Tensor, units: int, context_size: int, dropout: float) -> None:
        super().__init__()
        self.embedding = nn.Embedding.from_pretrained(embed_weights)
        self.vocab_size, embed_dim = embed_weights.shape
        self.rnn = nn.GRU((units * 2) + embed_dim, units)
        self.fc = nn.Linear(units + context_size + embed_dim, self.vocab_size)
        self.dropout = nn.Dropout(dropout)

    def forward(self, token: Tensor, dec_state: Tensor, context) -> Tuple[Tensor, Tensor]:
        token = token.unsqueeze(0)
        embedded = self.embedding(token)

        rnn_input = torch.cat((embedded, context), dim=2)
        output, dec_state = self.rnn(rnn_input, dec_state.unsqueeze(0))

        embedded = embedded.squeeze(0)
        output = output.squeeze(0)
        context = context.squeeze(0)

        # compute output using gru output, context vector, and embedding of previous output
        combined = torch.cat((output, context, embedded), dim=1)
        combined = self.dropout(combined)
        output = self.fc(combined)

        # return logits (rather than softmax activations) for compatibility with cross-entropy loss
        return output, dec_state.squeeze(0)


class EncoderDecoder(nn.Module):
    def __init__(self, device: torch.device,
                 embed_weights_src: Tensor, embed_weights_trg: Tensor,
                 rnn_units: int, attn_units: int,
                 dropout: float) -> None:
        super().__init__()
        self.encoder = Encoder(embed_weights_src, rnn_units, dropout)
        self.attention = Attention(rnn_units, attn_units)
        self.decoder = Decoder(embed_weights_trg, rnn_units, 2 * rnn_units, dropout)

        self.device = device
        self.target_vocab_size = self.decoder.vocab_size

    def forward(self, source: Tensor, target: Tensor, teacher_forcing: float = 0.5) -> Tensor:
        batch_size = source.shape[1]
        max_len = target.shape[0]
        enc_outputs, state = self.encoder(source)

        outputs = torch.zeros(max_len, batch_size, self.target_vocab_size).to(self.device)
        out = target[0, :]
        for t in range(1, max_len):
            context = self._compute_context(state, enc_outputs)
            out, state = self.decoder(out, state, context)
            outputs[t] = out
            teacher_force = random.random() < teacher_forcing
            out = (target[t] if teacher_force else out.max(1)[1])

        return outputs

    def _compute_context(self, dec_state, enc_outputs):
        weights = self.attention(dec_state, enc_outputs).unsqueeze(1)
        enc_outputs = enc_outputs.permute(1, 0, 2)
        return torch.bmm(weights, enc_outputs).permute(1, 0, 2)
