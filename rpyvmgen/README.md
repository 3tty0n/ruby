# rpyvmgen

Derive RPyYARV definitions from CRuby's own instruction definition file.

## What it does, and deliberately does not

```
  insns.def  --tool/ruby_vm/models-->  generate.rb  -->  rpyyarv/yarv_insns.py
                                                          (facts, generated)

  rpyyarv/yarv_map.py                                     (decisions, by hand)
       ^                                                       |
       +---------------- verify.rb cross-checks --------------+
```

Facts are derived from `insns.def` and involve no design judgement: operand
types, stack effects, which instructions branch, which are leaf, how the
specialized variants unfold.

At 19 mapped instructions a hand-written table would be perfectly serviceable;
generation earns its keep through drift detection, not through saved typing.

## Usage

```sh
make            # regenerate rpyyarv/yarv_insns.py
make verify     # check the hand-written map against insns.def
make check      # both
make diff       # is the generated file current?
```

## What verify.rb catches

Drift between the hand-written map and the pinned CRuby. Concretely:

- a mapped name that no longer exists in `insns.def` (renamed or removed)
- a specialized variant mapped directly instead of its base instruction
- an operand type on a mapped instruction that the loader neither transforms
  nor explicitly discards: the case that would otherwise mis-decode silently
- `yarv_insns.py` generated from a different Ruby version or instruction count

## Generated contents

`rpyyarv/yarv_insns.py`:

| Name | Contents |
|---|---|
| `RUBY_API_VERSION`, `SOURCE_REVISION`, `INSTRUCTION_COUNT` | provenance |
| `OPERANDS` | name -> operand type tuple; drives loader dispatch by type |
| `STACK` | name -> (pops, pushes); omitted when variadic |
| `VARIADIC` | stack effect not static, computed via `sp_inc` |
| `BRANCH` | carries an `OFFSET` operand — the mechanical branch test |
| `LEAF` / `LEAF_DYNAMIC` | pushes no frame; dynamic when it depends on an operand |
| `SPECIALIZED` | `getlocal_WC_0` etc. -> base name plus fixed operand values |

## Current figures (ruby_4_0)

```
  DEFINE_INSN                103
  operand-unified variants     6   (defs/opt_operand.def)
  branch instructions          6
  leaf                        51   (+6 decided at run time)
  variadic stack effect       21
  mapped by RPyYARV           19
```

