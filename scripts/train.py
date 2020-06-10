#!/usr/bin/env python3
import click
from click import Choice

from cleartext import PROJ_ROOT
from cleartext.data import WikiSmall
from cleartext.pipeline import Pipeline

# arbitrary choices
EOS_TOKEN = '<eos>'
SOS_TOKEN = '<sos>'
PAD_TOKEN = '<pad>'
UNK_TOKEN = '<unk>'

# fixed choices
MIN_FREQ = 2
NUM_SAMPLES = 4
CLIP = 1
MODELS_ROOT = PROJ_ROOT / 'models'


@click.command()
@click.option('--num_epochs', '-e', default=10, type=int, help='Number of epochs')
@click.option('--max_examples', '-n', default=50_000, type=int, help='Max number of training examples')
@click.option('--batch_size', '-b', default=32, type=int, help='Batch size')
@click.option('--embed_dim', '-d', default='50', type=Choice(['50', '100', '200', '300']), help='Embedding dimension')
@click.option('--trg_vocab', '-t', default=2_000, type=int, help='Max target vocabulary size')
@click.option('--rnn_units', '-r', default=100, type=int, help='Number of RNN units')
@click.option('--attn_units', '-a', default=100, type=int, help='Number of attention units')
@click.option('--dropout', '-p', default=0.3, type=float, help='Dropout probability')
def main(num_epochs: int, max_examples: int, batch_size: int,
         embed_dim: str, trg_vocab: int,
         rnn_units: int, attn_units: int,
         dropout: float) -> None:
    # initialize pipeline
    pipeline = Pipeline()
    print(f'Using {pipeline.device}')

    # load data
    print('Loading data')
    train_len, _, _ = pipeline.load_data(WikiSmall, max_examples)
    print(f'Loaded {train_len} training examples')

    # load embeddings
    print(f'Loading {embed_dim}-dimensional GloVe vectors')
    src_vocab_size, trg_vocab_size = pipeline.load_vectors(embed_dim, trg_vocab)
    print(f'Source vocabulary size: {src_vocab_size}')
    print(f'Target vocabulary size: {trg_vocab_size}')

    # prepare data
    pipeline.prepare_data(batch_size)

    # build model and prepare optimizer and loss
    print('Building model')
    trainable, total = pipeline.build_model(rnn_units, attn_units, dropout)
    print(f'Trainable parameters: {trainable} | Total parameters: {total}')

    # start training cycle
    print(f'Training model for {num_epochs} epochs')
    pipeline.train(num_epochs)


if __name__ == '__main__':
    main()
