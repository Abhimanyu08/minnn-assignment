from collections import defaultdict
import time
import random
import minnn as mn
import numpy as np
import argparse
import fasttext
# --
random.seed(12345)
np.random.seed(12345)
# --

# --
def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=str, default="data/sst-train.txt")
    parser.add_argument("--dev", type=str, default="data/sst-dev.txt")
    parser.add_argument("--test", type=str, default="data/sst-test.txt")
    parser.add_argument("--emb_size", type=int, default=64)
    parser.add_argument("--hid_size", type=int, default=64)
    parser.add_argument("--hid_layer", type=int, default=2)
    parser.add_argument("--word_drop", type=float, default=0.2)
    parser.add_argument("--emb_drop", type=float, default=0.333)
    parser.add_argument("--hid_drop", type=float, default=0.333)
    parser.add_argument("--iters", type=int, default=20)
    parser.add_argument("--lrate", type=float, default=0.01)
    parser.add_argument("--lrate_decay", type=float, default=1.)  # 1. means no decay!
    parser.add_argument("--mrate", type=float, default=0.85)
    parser.add_argument("--accu_step", type=int, default=10)  # this is actually batch size!
    parser.add_argument("--model", type=str, default="model.npz")  # save/load model name
    parser.add_argument("--do_gradient_check", type=int, default=0)
    parser.add_argument("--dev_output", type=str, default="output.dev.txt")  # output for dev
    parser.add_argument("--test_output", type=str, default="output.test.txt")  # output for dev
    parser.add_argument("--use_pretrained_embeddings", type = bool, default= False) #whether to use fasttext pretrained embeddings
    args = parser.parse_args()
    print(f"RUN: {vars(args)}")
    return args

def main():
    args = get_args()
    # --
    # Functions to read in the corpus
    w2i = defaultdict(lambda: len(w2i))
    t2i = defaultdict(lambda: len(t2i))
    UNK = w2i["<unk>"]
    def read_dataset(filename):
        with open(filename, "r") as f:
            for line in f:
                tag, words = line.lower().strip().split(" ||| ")
                yield ([w2i[x] for x in words.split(" ")], t2i[tag])

    # Read in the data
    train = list(read_dataset(args.train))
    w2i = defaultdict(lambda: UNK, w2i)
    dev = list(read_dataset(args.dev))
    test = list(read_dataset(args.test))
    nwords = len(w2i)
    ntags = len(t2i)
    # --
    # get i2w for outputting
    i2w = ["UNK"] * len(w2i)
    i2t = ["UNK"] * len(t2i)
    for _w, _i in w2i.items():
        if _i>0:
            i2w[_i] = _w
    for _t, _i in t2i.items():
        i2t[_i] = _t
    # --

    # Create a model (collection of parameters)
    model = mn.Model()
    trainer = mn.MomentumTrainer(model, lrate=args.lrate, mrate=args.mrate)

    # Define the model
    USE_PRETRAINED_EMBEDDINGS = args.use_pretrained_embeddings
    if USE_PRETRAINED_EMBEDDINGS:
        ft = fasttext.load_model('data/cc.en.100.bin')

    EMB_SIZE = ft.get_dimension() if USE_PRETRAINED_EMBEDDINGS else args.emb_size 
    HID_SIZE = ft.get_dimension() if USE_PRETRAINED_EMBEDDINGS else args.hid_size
    HID_LAY = args.hid_layer
    if not USE_PRETRAINED_EMBEDDINGS: W_emb = model.add_parameters((nwords, EMB_SIZE))  # Word embeddings
    W_h = [model.add_parameters((HID_SIZE, EMB_SIZE if lay == 0 else HID_SIZE), initializer='xavier_uniform') for lay in range(HID_LAY)]
    b_h = [model.add_parameters((HID_SIZE)) for lay in range(HID_LAY)]
    W_sm = model.add_parameters((ntags, HID_SIZE), initializer='xavier_uniform')  # Softmax weights
    b_sm = model.add_parameters((ntags))  # Softmax bias

        # A function to calculate scores for one value
    def calc_scores(words, is_training):
        # word drop in training
        if is_training:
            _word_drop = args.word_drop
            if _word_drop > 0.:
                words = [(UNK if s<_word_drop else w) for w,s in zip(words, np.random.random(len(words)))]
        # --
        if USE_PRETRAINED_EMBEDDINGS:
            emb = np.array([ft.get_word_vector(i2w[word]) for word in words])
            emb = mn.Tensor(emb, need_grad = False)
        else:
            emb = mn.lookup(W_emb, words)  # [len, D]
        emb = mn.dropout(emb, args.emb_drop, is_training)
        h = mn.sum(emb, axis=0)  # [D]
        for W_h_i, b_h_i in zip(W_h, b_h):
            h = mn.tanh(mn.dot(W_h_i, h) + b_h_i) # [D]
            h = mn.dropout(h, args.hid_drop, is_training)
        return mn.dot(W_sm, h) + b_sm  # [C]

    # dev/test
    dev_records = [-1, 0]  # best_iter, best_acc
    def do_test(_data, _iter: int, _name: str, _output: str = None):
        test_correct = 0.0
        _predictions = []
        for words, tag in _data:
            mn.reset_computation_graph()
            my_scores = calc_scores(words, False)
            scores = mn.forward(my_scores)
            predict = np.argmax(scores)
            _predictions.append(i2t[predict])
            if predict == tag:
                test_correct += 1
        # --
        cur_acc = test_correct/len(_data)
        post_ss = ""
        if _iter is not None:  # in training
            if cur_acc > dev_records[1]:
                dev_records[0], dev_records[1] = _iter, cur_acc
                model.save(args.model)  # save best!
            post_ss = f"; best=Iter{dev_records[0]}({dev_records[1]:.4f})"
        # --
        # output
        if _output is not None:
            assert len(_predictions) == len(_data)
            with open(_output, 'w') as fd:
                for _pred, _dd in zip(_predictions, _data):
                    _ws = " ".join([i2w[_widx] for _widx in _dd[0]])
                    fd.write(f"{_pred} ||| {_ws}\n")
        # --
        print(f"iter {_iter}: {_name} acc={cur_acc:.4f}" + post_ss)

    # start the training
    for ITER in range(args.iters):
        # Perform training
        random.shuffle(train)
        train_loss = 0.0
        start = time.time()
        _cur_steps = 0
        _accu_step = args.accu_step
        for words, tag in train:
            mn.reset_computation_graph()
            my_scores = calc_scores(words, True)
            my_loss = mn.log_loss(my_scores, tag)
            my_loss = my_loss * (1./_accu_step)  # div for batch
            _cur_loss = mn.forward(my_loss)
            train_loss += _cur_loss * _accu_step
            mn.backward(my_loss)
            _cur_steps += 1
            if _cur_steps % _accu_step == 0:
                trainer.update()  # update every accu_step
                # =====
                # check gradient
                # if True:
                if args.do_gradient_check:
                    # --
                    def _forw():
                        my_scores = calc_scores(words, False)
                        my_loss = mn.log_loss(my_scores, tag)
                        return mn.forward(my_loss), my_loss
                    # --
                    # computed grad
                    mn.reset_computation_graph()
                    arr_loss, my_loss = _forw()
                    mn.backward(my_loss)
                    # approx. grad
                    eps = 1e-3
                    for p in model.params:
                        if np.prod(p.shape[0]) == nwords:  # pick one word
                            pick_idx = np.random.choice(words) * EMB_SIZE + np.random.randint(EMB_SIZE)
                        else:
                            pick_idx = np.random.randint(len(p.data.reshape(-1)))
                        p.data.reshape(-1)[pick_idx] += eps
                        loss0, _ = _forw()
                        p.data.reshape(-1)[pick_idx] -= 2*eps
                        loss1, _ = _forw()
                        p.data.reshape(-1)[pick_idx] += eps
                        approx_grad = (loss0-loss1) / (2*eps)
                        calc_grad = p.get_dense_grad().reshape(-1)[pick_idx]
                        assert np.isclose(approx_grad, calc_grad, rtol=1.e-3, atol=1.e-6)
                    # clear
                    for p in model.params:
                        p.grad = None
                    print("Pass gradient checking!!")
            # =====
        print("iter %r: train loss/sent=%.4f, time=%.2fs" % (ITER, train_loss/len(train), time.time()-start))
        # dev
        do_test(dev, ITER, "dev")
        # lrate decay
        trainer.lrate *= args.lrate_decay
        # --
    # load best model and final test
    model.load(args.model)  # load best model
    do_test(dev, None, "dev", args.dev_output)
    do_test(test, None, "test", args.test_output)

# --
# MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 WHICH_XP=numpy python3 classifier.py
if __name__ == '__main__':
    # np.seterr(all='raise')
    main()
