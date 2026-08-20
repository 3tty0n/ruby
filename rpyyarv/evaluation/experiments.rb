# frozen_string_literal: true

module EvaluationConfig
  ENGINES = %w[cruby cruby+yjit cruby+zjit rpyyarv rpyyarv-jit].freeze
  REFERENCES = {
    "cruby" => "cruby",
    "yjit" => "cruby+yjit",
    "zjit" => "cruby+zjit",
    "truffleruby" => "truffleruby",
    "jruby" => "jruby"
  }.freeze
  GC_LIMITS = [16_384, 4096, 1024].freeze

  # Categories are disjoint by first match and intentionally file based.
  LOC_CATEGORIES = {
    "bytecode-interpreter" => %w[
      interp.py insns.py iseq.py loader.py optable.py rawiseq.py yarv_map.py
    ],
    "value-specialization" => %w[
      value.py classlib.py methods.py objects/*.py
    ],
    "boundary-trampoline" => %w[
      boot.py boot_shim.c boot_shim.h dispatch.py rubycall.py requires.py
    ],
    "gc-bridge" => %w[gcroots.py],
    "fiber-integration" => %w[fibers.py],
    "jit-runtime" => %w[frame.py targetrpyyarv.py]
  }.freeze

  CLAIMS = {
    "performance" => "End-to-end comparison across all five engines",
    "value-direct" => "Fast path versus residual CRuby call",
    "boundary" => "Frequency and identity of remaining CRuby delegation",
    "compatibility" => "Native, delegated, unsupported, and failed cases",
    "implementation" => "RPyYARV-owned implementation surface",
    "gc-fiber" => "Two-runtime integration under stress",
    "warmup-memory" => "Startup, compilation, RSS, traces, and bridges",
    "mechanism" => "Per-case explanation of wins and losses"
  }.freeze
end
