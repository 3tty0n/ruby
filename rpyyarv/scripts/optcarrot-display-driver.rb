# frozen_string_literal: true

# Keep this SDL/FFI adapter owned by CRuby. RPyYARV still runs optcarrot itself.
if false
  begin
    raise
  rescue
    retry
  end
end

module Optcarrot
  module SDL2
    attach_function :RenderSetVSync, :SDL_RenderSetVSync, [:pointer, :int], :int
  end

  module Driver
    def self.show_fps(colors, fps, palette)
      digits = [fps.to_s.length, 2].max
      width = (3 + digits) * 4

      (223 - 6 * SIZE).upto(223) do |y|
        (255 - width * SIZE).upto(255) do |x|
          color = colors[index = x + y * 256]
          r = ((color >> 16) & 0xff) / 4
          g = ((color >> 8) & 0xff) / 4
          b = (color & 0xff) / 4
          colors[index] = (color & 0xff000000) | (r << 16) | (g << 8) | b
        end
      end

      color =
        case
        when fps >= 90 then palette[0x19]
        when fps >= 60 then palette[0x11]
        when fps >= 55 then palette[0x28]
        else palette[0x16]
        end

      (3 + digits).times do |char|
        bits = FONT[char < digits ? fps / 10**(digits - char - 1) % 10 : char - digits + 10]
        5.times do |y|
          3.times do |x|
            next unless bits[x + y * 3] == 1
            colors[(224 + y - 6) * 256 + 256 + char * 4 + x - width] = color
          end
        end
      end
    end
  end

  class SDL2Video
    alias init_with_display_limit init

    def init
      @fps_limit = DISPLAY_FPS_LIMIT
      SDL2.SetHint("SDL_RENDER_VSYNC", "0")
      init_with_display_limit
      SDL2.RenderSetVSync(@renderer, 0)
      tick = SDL2.GetTicks * 1000
      @fps_ticks = [tick] * 11
      @title_fps = -1
      @present_every = @fps_limit > 0 ? [(@fps_limit + 29) / 30, 1].max : 8
      @frame_count = 0
      @pace_deadline = SDL2.GetTicks * @fps_limit
    end

    def tick(colors)
      if @fps_limit > 0
        @pace_deadline += 1000
        now = SDL2.GetTicks * @fps_limit
        wait = @pace_deadline - now
        SDL2.Delay((wait + @fps_limit - 1) / @fps_limit) if wait > 0
        now = SDL2.GetTicks * @fps_limit
        @pace_deadline = now if now - @pace_deadline > 1000
      end

      counter = SDL2.GetTicks * 1000
      @fps_ticks.rotate!(1)
      @fps_ticks[0] = counter
      elapsed = counter - @fps_ticks[1]
      fps = elapsed > 0 ? (10_000_000 + elapsed / 2) / elapsed : 0

      @frame_count += 1
      if @frame_count % @present_every == 0
        if fps != @title_fps
          SDL2.SetWindowTitle(@window, "optcarrot (#{fps} fps)")
          @title_fps = fps
        end

        Driver.cutoff_overscan(colors)
        Driver.show_fps(colors, fps, @palette) if @conf.show_fps
        @buf.write_array_of_uint32(colors)
        SDL2.UpdateTexture(@texture, nil, @buf, WIDTH * 4)
        SDL2.RenderClear(@renderer)
        SDL2.RenderCopy(@renderer, @texture, nil, nil)
        SDL2.RenderPresent(@renderer)
      end
      fps
    end
  end
end
