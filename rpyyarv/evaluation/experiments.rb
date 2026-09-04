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
  # Three decades of nursery, the dose-response range of hexapdf-jit-gc.org.
  GC_NURSERIES = [1 << 30, 4 << 20, 128 << 10].freeze

  # Runtime ablations: no rebuild, one named mechanism each.
  ABLATIONS = {
    "baseline" => {},
    "gc-no-hook" => { "RPYYARV_GC_NO_HOOK" => "1" },
    "gc-stress" => { "RPYYARV_GC_STRESS" => "1" },
    "fast-paths-off" => { "RPYYARV_FAST_PATHS" => "0" },
    # Each falls back to invalidating the whole cache, per dispatch/.
    "method-invalidation-global" =>
      { "RPYYARV_METHOD_INVALIDATION" => "global" },
    "class-invalidation-global" =>
      { "RPYYARV_CLASS_INVALIDATION" => "global" },
    "constant-invalidation-global" =>
      { "RPYYARV_CONSTANT_INVALIDATION" => "global" },
    # Pins trace eagerness, per interp/execute.py's EAGER_PARAMS/LAZY_PARAMS.
    "jit-params-eager" =>
      { "RPYYARV_JITPARAM" => "function_threshold=100,trace_eagerness=50" },
    "jit-params-lazy" =>
      { "RPYYARV_JITPARAM" => "function_threshold=1619,trace_eagerness=200" }
  }.freeze
  # gc-stress is orders of magnitude slower and is covered by EVAL=gc.
  DEFAULT_ABLATIONS = (ABLATIONS.keys - ["gc-stress"]).freeze

  # Ablations that need their own translation; run.rb only reports the recipe.
  BUILD_ABLATIONS = {
    "no-patch-0002" =>
      "make build-jit PYPY_PATCH_SKIP=0002 (gc mark forces vables)",
    "no-patch-0004" =>
      "make build-jit PYPY_PATCH_SKIP=0004 (extern forces virtualizable)",
    "no-quasiimmut" => "debug build with quasi-immutable fields disabled"
  }.freeze

  # First match wins; the hand taxonomy stays in docs, this is only a hint.
  DELEGATION_CLASSES = [
    [/refine|using/i, "structural/refinements"],
    [/C ext|\.bundle|\.so\b/i, "structural/c-extension"],
    [/Thread|Ractor/i, "structural/threads"],
    [/is not implemented/i, "engineering/loader"],
    [//, "engineering/runtime"]
  ].freeze

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
