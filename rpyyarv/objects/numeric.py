from rpyyarv.methods import W_CFunc


class W_Self(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return w_recv
