# rpyvmgen

Derive RPyYARV definitions from CRuby's own instruction definition file.

## What it does, and deliberately does not

```
  insns.def  --tool/ruby_vm/models-->  generate.rb  -->  rpyyarv/insns.py
                                                          (facts, generated)
                                                                |
  rpyyarv/yarv_map.py  (decisions, by hand) ----> rpyyarv/optable.py
       ^                                          (join, at import time)
       +---------------- verify.rb cross-checks --------+
```

Facts are derived from `insns.def` and involve no design judgement: opcode
numbers, operand types, stack effects, which instructions branch, which are
leaf, how the specialized variants unfold.

Opcode is the index into `insns.def`, so the numbering is a fact too and
covers all 103 instructions. `yarv_map.py` then only has to say which ones
RPyYARV implements and how it encodes their operands.

At 19 implemented instructions a hand-written table would be perfectly
serviceable; generation earns its keep through drift detection, not through
saved typing.

## Usage

```sh
make            # regenerate rpyyarv/insns.py
make verify     # check the hand-written decisions against insns.def
make check      # both
make diff       # is the generated file current?
```

## What verify.rb catches

Drift between the hand-written decisions and the pinned CRuby. Concretely:

- an implemented name that no longer exists in `insns.def` (renamed or removed)
- a specialized variant implemented directly instead of its base instruction
- an operand type that the loader neither transforms nor explicitly discards:
  the case that would otherwise mis-decode silently
- an `EMIT` position past the end of the instruction's operand list, or listed
  twice
- `insns.py` generated from a different Ruby version or instruction count

`optable.py` covers the remaining direction: a name in `yarv_map.EMIT` that
`insns.py` does not define raises at import.

## Generated contents

`rpyyarv/insns.py`, every table indexed by opcode:

| Name | Contents |
|---|---|
| `RUBY_API_VERSION`, `SOURCE_REVISION`, `INSTRUCTION_COUNT` | provenance |
| `NOP`, `GETLOCAL`, ... | opcode constants, one per instruction |
| `NAMES`, `NAME_TO_OP` | the only place instruction names appear |
| `T_VALUE`, ... / `TYPE_NAMES` | operand type codes |
| `OPERAND_TYPES` | operand type codes of each instruction, in order |
| `STACK_POP` / `STACK_PUSH` | static stack effect; `-1` when variadic |
| `IS_BRANCH` | carries an `OFFSET` operand: the mechanical branch test |
| `IS_LEAF` / `IS_LEAF_DYNAMIC` | pushes no frame; dynamic when it depends on an operand |
| `SPEC_BASE` / `SPEC_FILL` | `getlocal_WC_0` etc. -> base opcode plus fixed `(position, value)` |

## Current figures (ruby_4_0)

```
  DEFINE_INSN                103
  operand-unified variants     6   (defs/opt_operand.def)
  branch instructions          6
  leaf                        51   (+6 decided at run time)
  variadic stack effect       21
  implemented by RPyYARV      19
```
