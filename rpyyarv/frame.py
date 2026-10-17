from rpyyarv.objects.main import w_main
from rpyyarv.objects.transparent import w_nil
from rpyyarv.rlib import hint, unroll_safe


_EMPTY_SLOTS = []


class Frame(object):
    # Keep small frames in one allocation; larger ones use overflow slots.
    _virtualizable_ = ['sp', 'slot0', 'slot1', 'slot2', 'slot3',
                      'slot4', 'slot5', 'slot6', 'slot7', 'extra[*]']

    @unroll_safe
    def __init__(self, iseq, w_self=w_main):
        self = hint(self, access_directly=True, fresh_virtualizable=True)
        # sp is absolute: the operand stack starts after the locals.
        self.sp = iseq.nlocals
        self.w_self = w_self
        self.slot0 = w_nil if iseq.nlocals > 0 else None
        self.slot1 = w_nil if iseq.nlocals > 1 else None
        self.slot2 = w_nil if iseq.nlocals > 2 else None
        self.slot3 = w_nil if iseq.nlocals > 3 else None
        self.slot4 = w_nil if iseq.nlocals > 4 else None
        self.slot5 = w_nil if iseq.nlocals > 5 else None
        self.slot6 = w_nil if iseq.nlocals > 6 else None
        self.slot7 = w_nil if iseq.nlocals > 7 else None
        size = iseq.nlocals + iseq.stack_max - 8
        if size > 0:
            self.extra = [None] * size
            i = 8
            while i < iseq.nlocals:
                index = i - 8
                assert index >= 0
                self.extra[index] = w_nil
                i += 1
        else:
            self.extra = _EMPTY_SLOTS

    def getlocal(self, index):
        return self._getslot(index)

    def setlocal(self, index, w_x):
        self._setslot(index, w_x)

    def peek(self, index):
        return self._getslot(index)

    def push(self, w_x):
        sp = self.sp
        assert sp >= 0
        self._setslot(sp, w_x)
        self.sp = sp + 1

    def pop(self):
        sp = self.sp - 1
        assert sp >= 0
        w_x = self._getslot(sp)
        self._setslot(sp, None)
        self.sp = sp
        return w_x

    def _getslot(self, index):
        assert index >= 0
        if index == 0:
            return self.slot0
        elif index == 1:
            return self.slot1
        elif index == 2:
            return self.slot2
        elif index == 3:
            return self.slot3
        elif index == 4:
            return self.slot4
        elif index == 5:
            return self.slot5
        elif index == 6:
            return self.slot6
        elif index == 7:
            return self.slot7
        index -= 8
        assert index >= 0
        return self.extra[index]

    def _setslot(self, index, w_x):
        assert index >= 0
        if index == 0:
            self.slot0 = w_x
        elif index == 1:
            self.slot1 = w_x
        elif index == 2:
            self.slot2 = w_x
        elif index == 3:
            self.slot3 = w_x
        elif index == 4:
            self.slot4 = w_x
        elif index == 5:
            self.slot5 = w_x
        elif index == 6:
            self.slot6 = w_x
        elif index == 7:
            self.slot7 = w_x
        else:
            index -= 8
            assert index >= 0
            self.extra[index] = w_x
