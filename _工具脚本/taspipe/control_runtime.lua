-- Batch interpreter, not an idle StateSession. Input is data, never Lua source.
local dir = __CONTROL_WORKDIR__
local NULL, ARRAY = {}, {}
local function array(t) return setmetatable(t or {}, ARRAY) end
local function readfile(path)
    local f, err = io.open(path, "rb")
    if not f then error("open " .. path .. ": " .. tostring(err)) end
    local s = f:read("*a")
    assert(f:close())
    return s
end
local function writefile(path, text)
    local f, err = io.open(path, "wb")
    if not f then error("open " .. path .. ": " .. tostring(err)) end
    assert(f:write(text)); assert(f:flush()); assert(f:close())
end
local function exists(path)
    local f = io.open(path, "rb")
    if not f then return false end
    assert(f:close()); return true
end
local function decode(s)
    local pos = 1
    local function count()
        local a, b, n = s:find("^(%d+):", pos)
        if not a then error("invalid wire length at " .. pos) end
        pos = b + 1
        return tonumber(n)
    end
    local parse
    parse = function(depth)
        if depth > 100 then error("wire nesting too deep") end
        local tag = s:sub(pos, pos); pos = pos + 1
        if tag == "z" then return NULL end
        if tag == "t" then return true end
        if tag == "f" then return false end
        local n = count()
        if tag == "s" or tag == "n" then
            local raw = s:sub(pos, pos + n - 1); pos = pos + n
            if #raw ~= n then error("truncated wire scalar") end
            if tag == "n" then return assert(tonumber(raw), "invalid number") end
            if n % 2 ~= 0 or raw:find("[^0-9a-f]") then error("invalid UTF-8 hex string") end
            return (raw:gsub("..", function(x) return string.char(tonumber(x, 16)) end))
        elseif tag == "a" then
            local t = array()
            for i = 1, n do t[i] = parse(depth + 1) end
            return t
        elseif tag == "d" then
            local t = {}
            for _ = 1, n do
                local k = parse(depth + 1)
                if type(k) ~= "string" or t[k] ~= nil then error("invalid/duplicate wire key") end
                t[k] = parse(depth + 1)
            end
            return t
        end
        error("invalid wire tag: " .. tag)
    end
    local value = parse(0)
    if pos ~= #s + 1 then error("trailing wire data") end
    return value
end
local function quote(s)
    return '"' .. s:gsub('[%z\1-\31\\"]', function(c)
        if c == '"' then return '\\"' end
        if c == '\\' then return '\\\\' end
        return string.format("\\u%04x", string.byte(c))
    end) .. '"'
end
local function json(v)
    if v == NULL or v == nil then return "null" end
    local typ = type(v)
    if typ == "string" then return quote(v) end
    if typ == "boolean" then return v and "true" or "false" end
    if typ == "number" then
        if v ~= v or v == math.huge or v == -math.huge then error("nonfinite JSON number") end
        return string.format("%.17g", v)
    end
    if typ ~= "table" then error("unsupported JSON type " .. typ) end
    local out = {}
    if getmetatable(v) == ARRAY then
        for i = 1, #v do out[i] = json(v[i]) end
        return "[" .. table.concat(out, ",") .. "]"
    end
    for k, val in pairs(v) do out[#out + 1] = quote(tostring(k)) .. ":" .. json(val) end
    return "{" .. table.concat(out, ",") .. "}"
end
local function publish(path, value)
    local tmp = path .. ".tmp"
    writefile(tmp, json(value) .. "\n")
    if exists(path) then assert(os.remove(path)) end
    assert(os.rename(tmp, path))
end

local program, eventfile, current, gate
local identity_gate = false
local initialized = false
local tail_probe = nil
-- wire 协议把 Python 的 None 编成 NULL 哨兵（_wire 的 "z"），不是 Lua 的 nil；
-- 只判 `~= nil` 会把"这一趟不采样"读成"有配置"，接着 integer(tail_probe.from) 当场炸掉整趟。
-- 同一条约定在 domain/expect 那两处是按 nil+NULL 双判的，这里补成同一个函数。
local function present(v) return v ~= nil and v ~= NULL end
local started, finished, pending = false, false, nil
local index, advances, consumed, seq = 1, 0, 0, 0
local checkpoints = {}
local movie_owned = false
local result = {status="failed", execution="fail", completion="inconclusive", reason="not started",
                frames_advanced=0, movie={expected_inputs=0, consumed_inputs=0, sync="unverified"},
                artifacts=array(), checkpoints=checkpoints, audio=false, tail_samples=array()}
local function frame() return emu.framecount() end
local function event(kind, data)
    local e = data or {}
    e.kind, e.frame, e.frames_advanced, e.consumed_inputs = kind, frame(), advances, consumed
    if current then e.step_id, e.op = current.id, current.op end
    assert(eventfile:write(json(e) .. "\n")); assert(eventfile:flush())
end
local function heartbeat(phase)
    writefile(dir .. "/heartbeat.txt", string.format("%d %s %d %d\n", advances, phase, frame(), consumed))
end
local function integer(n, what, minimum, maximum)
    if type(n) ~= "number" or n ~= math.floor(n) or n < minimum or (maximum and n > maximum) then
        error("invalid " .. what .. ": " .. tostring(n))
    end
    return n
end
local function same_frame(before, what)
    if frame() ~= before then error(what .. " advanced game frame unexpectedly") end
end
local function asset(path)
    result.artifacts[#result.artifacts + 1] = path
end
local function save(path)
    local before = frame()
    if exists(path) then assert(os.remove(path)) end
    savestate.save(path, true)
    local f = assert(io.open(path, "rb"), "savestate.save produced no file: " .. path)
    local sig = f:read(2); local size = f:seek("end"); assert(f:close())
    if sig ~= "PK" or size < 22 then error("invalid state container: " .. path) end
    same_frame(before, "save")
end
local function shot(path)
    local before = frame()
    -- frameskip 下截图已实测安全（skip 0 与 skip 8 连续 300 张 PNG 逐字节相同，NesHawk）；换核心须重跑该对照。
    client.screenshot(path)
    -- Official 2.8 TakeScreenshot saves synchronously; never 'flush' by advancing.
    local f = assert(io.open(path, "rb"), "screenshot produced no file: " .. path)
    local sig = f:read(8); local size = f:seek("end")
    assert(f:seek("set", math.max(0, size - 12)))
    local ending = f:read(12); assert(f:close())
    if sig ~= "\137PNG\13\10\26\10" or ending ~= "\0\0\0\0IEND\174\66\96\130" then
        error("incomplete PNG (no extra frame allowed): " .. path)
    end
    same_frame(before, "screenshot")
    asset(path)
end
local function domains()
    local out = {}
    for _, name in pairs(memory.getmemorydomainlist()) do out[name] = true end
    return out
end
local function descriptor(x)
    local domain = x.domain
    if domain == nil or domain == NULL then domain = memory.getcurrentmemorydomain() end
    if type(domain) ~= "string" or not domains()[domain] then
        error("unknown memory domain: " .. tostring(domain))
    end
    -- getmemorydomainsize silently falls back on unknown names; whitelist first.
    local size = memory.getmemorydomainsize(domain)
    local width = integer(x.width, "width", 1, 4)
    if width ~= 1 and width ~= 2 and width ~= 4 then error("width must be 1/2/4") end
    local addr = integer(x.addr, "addr", 0)
    if addr + width > size then error("memory range exceeds domain: " .. domain) end
    if x.endian ~= "little" and x.endian ~= "big" then error("invalid endian") end
    return {id=x.id, domain=domain, addr=addr, width=width, endian=x.endian}
end
local function readvalue(d)
    local value = 0
    for i = 0, d.width - 1 do
        local b = memory.read_u8(d.addr + i, d.domain)
        integer(b, "read byte", 0, 255)
        local power = d.endian == "little" and i or (d.width - 1 - i)
        value = value + b * 256 ^ power
    end
    return value
end
local function writevalue(d, value)
    for i = 0, d.width - 1 do
        local power = d.endian == "little" and i or (d.width - 1 - i)
        memory.write_u8(d.addr + i, math.floor(value / 256 ^ power) % 256, d.domain)
    end
end
local function compare(actual, item)
    local cmp = item.cmp
    if cmp == "eq" then return actual == item.value end
    if cmp == "ne" then return actual ~= item.value end
    if cmp == "ge" then return actual >= item.value end
    if cmp == "le" then return actual <= item.value end
    error("invalid comparator")
end
local function sample(items, checking)
    local values, all = array(), true
    for _, item in ipairs(items) do
        local d = descriptor(item)
        d.actual = readvalue(d)
        if checking then
            integer(item.value, "check value", 0, 256 ^ d.width - 1)
            d.expected, d.cmp = item.value, item.cmp
            d.pass = compare(d.actual, item)
            all = all and d.pass
        end
        values[#values + 1] = d
    end
    return values, all
end
-- latch 判据：重放期间逐帧求值。
-- latch=true（"once"）：首次成立就记下帧号并停掉这一条。只在末帧求值会把"通关后回到
-- 标题/重开游戏"的电影判成 fail（3232 塞尔达带 "Uses a game restart sequence"，
-- 5628 洛克人X2 末帧是标题画面），所以"中途成立"必须是一等模式。
-- latch="terminal"：只认"从某帧起一直到收尾不再回落"的最后一段。两者不能混用：
-- 11-21 实测 3232 的 $051C 在 52343 帧就摸到过 100（中段淡出），74420 帧起才不回落到 0，
-- 用 once 会把中段淡出当成通关。terminal 同时记 false_frames（不成立的帧数）和
-- fell_back（成立后又回落的次数）；自始就成立（false_frames==0）不算转折，判 fail。
local latch_active, latch_witness, term_active = array(), {}, {}
local function latch_mode(item)
    if item.latch == true then return "once" end
    if item.latch == "terminal" then return "terminal" end
    return nil
end
local function latch_setup()
    for i, item in ipairs(program.completion or {}) do
        local mode = latch_mode(item)
        if mode then
            local d = descriptor(item)
            integer(item.value, "check value", 0, 256 ^ d.width - 1)
            if type(item.cmp) ~= "string" then error("latch check needs a comparator") end
            local entry = {idx = i, item = item, d = d, mode = mode, open = false, start = 0,
                           value = 0, false_frames = 0, fell_back = 0}
            if mode == "once" then
                latch_active[#latch_active + 1] = entry
            else
                term_active[entry.idx] = entry
            end
        end
    end
end
local function latch_poll()
    for k = #latch_active, 1, -1 do
        local p = latch_active[k]
        local value = readvalue(p.d)
        if compare(value, p.item) then
            -- 记 advances（本任务真实推进的帧数）而不是 emu.framecount()：
            -- 从存档开跑时后者带着存档自带的帧号，控制层就没法核对" witness 落在本任务内"。
            p.frame, p.value = advances, value
            latch_witness[p.idx] = p
            table.remove(latch_active, k)
            event("completion_latch", {id = p.item.id, value = value,
                                       expected = p.item.value, cmp = p.item.cmp})
        end
    end
    for _, p in pairs(term_active) do
        local value = readvalue(p.d)
        if compare(value, p.item) then
            if not p.open then p.open, p.start, p.value = true, advances, value end
        else
            p.false_frames = p.false_frames + 1
            if p.open then p.open, p.fell_back = false, p.fell_back + 1 end
        end
    end
end
local function completion_verdict()
    if #(program.completion or {}) == 0 then return "inconclusive", array() end
    local values, all = array(), true
    for i, item in ipairs(program.completion) do
        local d = descriptor(item)
        if item.latch == "terminal" then
            local p = term_active[i]
            d.expected, d.cmp, d.latch = item.value, item.cmp, "terminal"
            -- 收尾必须仍成立；false_frames==0 表示这条判据自始成立，不构成"由未达成
            -- 变成达成"的转折，判 fail 而不是判 pass。
            d.actual = p and p.open and p.value or readvalue(d)
            d.pass = p ~= nil and p.open == true and p.false_frames > 0
            d.terminal_start = p and p.open and p.start or NULL
            d.false_frames, d.fell_back = p and p.false_frames or 0, p and p.fell_back or 0
            if not d.pass then all = false end
        elseif item.latch == true then
            local w = latch_witness[i]
            d.expected, d.cmp, d.latch = item.value, item.cmp, true
            d.actual, d.pass = (w and w.value) or NULL, w ~= nil
            d.witness_frame = (w and w.frame) or NULL
            if not w then all = false end
        else
            d.actual = readvalue(d)
            integer(item.value, "check value", 0, 256 ^ d.width - 1)
            d.expected, d.cmp = item.value, item.cmp
            d.pass = compare(d.actual, item)
            all = all and d.pass
        end
        values[#values + 1] = d
    end
    return (all and "pass" or "fail"), values
end
local function inactive(op)
    if movie_owned or movie.mode() ~= "INACTIVE" then error(op .. " requires takeover first") end
end
local function stop_movie()
    if movie.mode() ~= "INACTIVE" then movie.stop() end
    if movie.mode() ~= "INACTIVE" then error("movie.stop did not deactivate movie") end
    movie_owned = false
    client.clearautohold()
end
local function buttons(players)
    local full, selected, analog, prefixed = joypad.get(), {}, {}, false
    for name, value in pairs(full) do
        if name:match("^P%d+ ") then prefixed = true end
        if type(value) == "boolean" then selected[name] = false
        elseif program.system == "GBA" and program.core == "mGBA" and
                (name == "Tilt X" or name == "Tilt Y" or name == "Tilt Z" or name == "Light Sensor") then
            -- MGBAHawk.GBAController declares these four axis neutrals as zero.
            analog[name] = 0
        else error("no known neutral for analog control: " .. name) end
    end
    for player, keys in pairs(players or {}) do
        local p = tonumber(player)
        integer(p, "player", 1, 16)
        for _, name in ipairs(keys) do
            local key = "P" .. p .. " " .. name
            if not prefixed and p == 1 then key = name end
            if type(full[key]) ~= "boolean" then error("missing controller topology button: " .. key) end
            selected[key] = true
        end
    end
    return {digital=selected, analog=analog}
end
local function apply_buttons(selected)
    joypad.set(selected.digital)
    local actual = joypad.getimmediate()
    for k, v in pairs(selected.digital) do
        if actual[k] ~= v then error("joypad override readback mismatch: " .. k) end
    end
    if next(selected.analog) then
        if joypad.setanalog == nil then error("required API missing: joypad.setanalog") end
        joypad.setanalog(selected.analog)
        actual = joypad.get()
        for k, v in pairs(selected.analog) do
            if actual[k] ~= v then error("analog neutral readback mismatch: " .. k) end
        end
    end
end
local function cpu_registers()
    local getnames, getvalue = emu.getregisters, emu.getregister
    if (type(getnames) ~= "function" and type(getnames) ~= "userdata") or
            (type(getvalue) ~= "function" and type(getvalue) ~= "userdata") then
        error("CPU register API unavailable")
    end
    local names, values = getnames(), {}
    if type(names) ~= "table" then error("CPU register list is not a table") end
    local ordered = {}
    for name in pairs(names) do
        if type(name) ~= "string" or name == "" or #name > 80 then error("invalid CPU register name") end
        if #ordered >= 256 then error("CPU register list exceeds 256 entries") end
        ordered[#ordered + 1] = name
    end
    if #ordered == 0 then error("CPU register list is empty") end
    table.sort(ordered)
    for _, name in ipairs(ordered) do
        local value = getvalue(name)
        if type(value) ~= "number" or value ~= math.floor(value) then
            error("CPU register is not an integer: " .. name)
        end
        values[name] = value
    end
    return values
end
local function dump_ram(path, requested_domain, start, count)
    local name = requested_domain
    if name == nil or name == NULL then name = memory.getcurrentmemorydomain() end
    if type(name) ~= "string" or not domains()[name] then
        error("unknown RAM domain: " .. tostring(name))
    end
    local size = integer(memory.getmemorydomainsize(name), "RAM size", 1)
    start = integer(start or 0, "RAM start", 0, size - 1)
    count = integer(count or (size - start), "RAM bytes", 1, size - start)
    local f = assert(io.open(path, "wb"))
    local read_method = "byte"
    if type(memory.read_bytes_as_binary_string) == "function" or
            type(memory.read_bytes_as_binary_string) == "userdata" then
        local data = memory.read_bytes_as_binary_string(start, count, name)
        if type(data) ~= "string" or #data ~= count then
            error("binary RAM read length mismatch: " .. tostring(name))
        end
        assert(f:write(data)); read_method = "bulk"
    else
        local chunk = {}
        for addr = start, start + count - 1 do
            chunk[#chunk + 1] = string.char(integer(memory.read_u8(addr, name), "RAM byte", 0, 255))
            if #chunk == 4096 then assert(f:write(table.concat(chunk))); chunk = {} end
        end
        if #chunk > 0 then assert(f:write(table.concat(chunk))) end
    end
    assert(f:close()); asset(path)
    return {path=path, domain=name, start=start, bytes=count, read_method=read_method}
end
local function seed_ram(path, requested_domain, start, count)
    local name = requested_domain
    if type(name) ~= "string" or not domains()[name] then
        error("unknown RAM domain: " .. tostring(name))
    end
    local size = integer(memory.getmemorydomainsize(name), "RAM size", 1)
    start = integer(start, "RAM start", 0, size - 1)
    count = integer(count, "RAM bytes", 1, size - start)
    local data = readfile(path)
    if #data ~= count then error("seed RAM length mismatch: " .. tostring(#data) .. " != " .. tostring(count)) end
    local before = frame()
    for i = 1, count do memory.write_u8(start + i - 1, string.byte(data, i), name) end
    for i = 1, count do
        local actual = integer(memory.read_u8(start + i - 1, name), "seed RAM byte", 0, 255)
        if actual ~= string.byte(data, i) then
            error("seed RAM readback mismatch at offset " .. tostring(i - 1))
        end
    end
    same_frame(before, "seed_ram")
    return {domain=name, start=start, bytes=count, sha256_verified_by_runner=true}
end
local function patch(writes)
    local before, validated, occupied = frame(), array(), {}
    for _, w in ipairs(writes) do
        local d = descriptor(w)
        d.value = integer(w.value, "write value", 0, 256 ^ d.width - 1)
        d.before = readvalue(d)
        if w.expect ~= nil and w.expect ~= NULL then
            integer(w.expect, "expect", 0, 256 ^ d.width - 1)
            d.expect = w.expect
            if d.before ~= w.expect then
                event("patch_expect_failed", {write=d})
                error("patch expect mismatch; no writes applied")
            end
        end
        occupied[d.domain] = occupied[d.domain] or {}
        for a = d.addr, d.addr + d.width - 1 do
            if occupied[d.domain][a] then error("overlapping patch writes are ambiguous") end
            occupied[d.domain][a] = true
        end
        validated[#validated + 1] = d
    end
    local rollback = dir .. "/patch_rollback.state"
    save(rollback)
    local ok, err = pcall(function()
        for _, d in ipairs(validated) do writevalue(d, d.value) end
        for _, d in ipairs(validated) do
            d.after = readvalue(d)
            if d.after ~= d.value then error("patch readback mismatch: " .. d.domain .. ":" .. d.addr) end
        end
    end)
    if not ok then
        local restored, why = pcall(function()
            savestate.load(rollback, true)
            -- Some writable ROM domains are excluded from Core.bin snapshots.
            for _, d in ipairs(validated) do
                if readvalue(d) ~= d.before then writevalue(d, d.before) end
            end
            savestate.load(rollback, true)
            same_frame(before, "patch rollback")
            for _, d in ipairs(validated) do
                if readvalue(d) ~= d.before then error("rollback readback mismatch") end
            end
        end)
        event("patch_failed", {writes=validated, rollback=restored, rollback_error=why or NULL})
        error(tostring(err) .. (restored and "; rolled back" or "; ROLLBACK FAILED: " .. tostring(why)))
    end
    same_frame(before, "patch")
    event("patch_written", {writes=validated, evidence="write readback only; not gameplay proof"})
end
local function state_gate(original, continuation)
    seq = seq + 1
    event("state_load_begin", {seq=seq, original=original, continuation=continuation})
    local roundtrip = dir .. "/artifacts/roundtrip_" .. seq .. ".state"
    savestate.load(original, true)
    event("state_load_done", {seq=seq, frame=frame()})
    local loaded_frame = frame()
    save(roundtrip)
    gate = {seq=seq, frame=loaded_frame, continuation=continuation}
    publish(dir .. "/gate_request_" .. seq .. ".json", {token=program.token, seq=seq,
            original=original, roundtrip=roundtrip, frame=loaded_frame})
    event("state_admission_wait", {seq=seq, original=original, roundtrip=roundtrip})
end
local function gate_poll()
    same_frame(gate.frame, "paused state admission")
    local path = dir .. "/gate_reply_" .. gate.seq .. ".json"
    if not exists(path) then return false end
    -- Python writes this tiny fixed schema; parse exact JSON scalars, not code.
    local text = readfile(path)
    local token = text:match('"token"%s*:%s*"([0-9a-f]+)"')
    local reply_seq = tonumber(text:match('"seq"%s*:%s*(%d+)'))
    if token ~= program.token or reply_seq ~= gate.seq then return false end
    local allow = text:match('"allow"%s*:%s*(%a+)')
    if allow ~= "true" then error("state Core.bin/BizVersion admission rejected") end
    event("state_admitted", {seq=gate.seq})
    local continuation = gate.continuation
    gate = nil
    if continuation == "load" then
        event("step_done"); index = index + 1; current = nil
    end
    return true
end
local function finish_step(data)
    event("step_done", data)
    index, current = index + 1, nil
end
local function request_advance(selected, replay)
    local before = frame()
    if replay then
        if not movie_owned or program.start.kind ~= "movie" or movie.mode() ~= "PLAY" then
            error("replay requires the initial movie still playing")
        end
        if consumed >= result.movie.expected_inputs or before >= movie.length() then
            error("replay exhausted original movie inputs")
        end
        local mnemonic = movie.getinputasmnemonic(before)
        if type(mnemonic) ~= "string" or mnemonic == "" then error("movie input missing at current frame") end
        pending = {before=before, replay=true, input_index=before, mnemonic=mnemonic}
    else
        inactive("controlled advance")
        apply_buttons(selected)
        pending = {before=before, replay=false}
    end
    return "advance"
end
local function after_advance()
    if not pending then return end
    local p = pending
    pending = nil
    local delta = frame() - p.before
    if delta > 0 then advances = advances + delta end
    if delta ~= 1 then error("expected exactly one game frame; got " .. delta) end
    if p.replay then consumed = consumed + 1 end
    event("frame_advanced", {replay=p.replay, input_index=p.input_index, mnemonic=p.mnemonic})
    latch_poll()
    if present(tail_probe) then
        local f = frame()
        if f >= tail_probe.from and (f - tail_probe.from) % tail_probe.stride == 0
                and #result.tail_samples < tail_probe.max then
            local path = dir .. string.format("/artifacts/tail/f%06d.png", f)
            shot(path)
            result.tail_samples[#result.tail_samples + 1] = {frame=f, screenshot=path}
        end
    end
    if program.capture then
        shot(dir .. string.format("/artifacts/frames/f%04d.png", advances - 1))
    end
    if current.op == "input" then current._left = current._left - 1
    elseif current.op == "until" then current._elapsed = current._elapsed + 1
    else current._left = current._left - 1 end
end
local function identity_poll()
    local path = dir .. "/identity_reply.json"
    if not exists(path) then return false end
    local text = readfile(path)
    local token = text:match('"token"%s*:%s*"([0-9a-f]+)"')
    local allow = text:match('"allow"%s*:%s*(%a+)')
    if token ~= program.token then return false end
    if allow ~= "true" then error("zero-frame core identity rejected") end
    event("core_identity_admitted", {frame=frame(), state=dir .. "/artifacts/identity.state"})
    identity_gate = false
    return true
end
local function initialize()
    program = decode(readfile(dir .. "/program.dat"))
    result.token = program.token
    eventfile = assert(io.open(dir .. "/events.jsonl", "wb"))
    local required = {emu={"framecount", "frameadvance", "yield", "getsystemid"},
        client={"pause", "unpause", "screenshot", "exit", "frameskip", "setscreenshotosd", "clearautohold"},
        movie={"mode", "stop", "length", "setreadonly", "getreadonly", "getinputasmnemonic"},
        joypad={"get", "getimmediate", "set"},
        memory={"getmemorydomainlist", "getmemorydomainsize", "getcurrentmemorydomain", "read_u8", "write_u8"},
        savestate={"save", "load"}}
    local api_types = {}
    for lib, names in pairs(required) do
        api_types[lib] = {library_type=type(_G[lib])}
        for _, name in ipairs(names) do api_types[lib][name] = type(_G[lib] and _G[lib][name]) end
    end
    event("runtime_api", {types=api_types})
    for lib, names in pairs(required) do
        for _, name in ipairs(names) do
            if _G[lib] == nil or (api_types[lib][name] ~= "function" and api_types[lib][name] ~= "userdata") then
                error("required API missing: " .. lib .. "." .. name .. " type=" .. api_types[lib][name])
            end
        end
    end
    client.pause(); client.setscreenshotosd(false); client.clearautohold()
    local skip = integer(program.frameskip or 0, "frameskip", 0, 60)
    client.frameskip(skip)
    tail_probe = program.tail_probe
    if present(tail_probe) then
        integer(tail_probe.from, "tail_probe.from", 0)
        integer(tail_probe.stride, "tail_probe.stride", 1, 600)
        integer(tail_probe.max, "tail_probe.max", 1, 400)
    end
    if emu.getsystemid() ~= program.system then error("loaded system does not match program.system") end
    event("runtime_started", {system=emu.getsystemid(), requested_core=program.core})
    if frame() ~= 0 then error("core identity requires pristine frame zero") end
    local identity = dir .. "/artifacts/identity.state"
    save(identity); asset(identity)
    publish(dir .. "/identity_request.json", {token=program.token, state=identity, frame=frame()})
    event("core_identity_wait", {state=identity, requested_core=program.core})
    identity_gate = true
    initialized = true
end
local function start_session()
    if frame() ~= 0 then error("start session requires frame zero after identity admission") end
    local start = program.start
    event("session_start", {start_kind=start.kind, mode=movie.mode(), frame_zero=frame()})
    if start.kind == "state" then
        stop_movie()
        state_gate(start.path, "initial")
    elseif start.kind == "movie" then
        if frame() ~= 0 then error("movie startup already consumed frames; refusing hidden progress") end
        if movie.mode() ~= "PLAY" then
            event("movie_start_rejected", {mode=movie.mode(), input_length=movie.length(),
                                           readonly=movie.getreadonly()})
            error("initial movie is not playing")
        end
        event("movie_start_observed", {phase="before_readonly", mode=movie.mode(),
                                       input_length=movie.length(), readonly=movie.getreadonly()})
        movie.setreadonly(true)
        event("movie_start_observed", {phase="after_readonly", mode=movie.mode(),
                                       input_length=movie.length(), readonly=movie.getreadonly()})
        if not movie.getreadonly() then error("movie readonly unavailable") end
        local input_length = movie.length()
        event("movie_start_observed", {phase="after_length", mode=movie.mode(),
                                       input_length=input_length, readonly=movie.getreadonly()})
        if input_length ~= start.movie_frames then error("movie length differs from materialized input count") end
        result.movie.expected_inputs = start.movie_frames
        movie_owned = true
        event("movie_session_ready", {mode=movie.mode(), input_length=input_length,
                                      readonly=movie.getreadonly()})
    elseif start.kind == "boot" then
        if movie.mode() ~= "INACTIVE" or frame() ~= 0 then error("boot start is not pristine frame zero") end
    else error("invalid start kind") end
    latch_setup()
    started = true
end
local function finalize()
    local verdict, values = completion_verdict()
    result.completion = verdict
    local witness = {}
    for i, w in pairs(latch_witness) do
        witness[program.completion[i].id] = {frame = w.frame, value = w.value}
    end
    for i, p in pairs(term_active) do
        if p.open and p.false_frames > 0 then
            witness[program.completion[i].id] = {frame = p.start, value = p.value,
                                                 false_frames = p.false_frames,
                                                 fell_back = p.fell_back}
        end
    end
    if next(witness) ~= nil then result.completion_witness = witness end
    event("completion", {checks=values, verdict=result.completion})
    -- End movie association before saving a reusable, controlled final state.
    stop_movie()
    local before = frame()
    save(dir .. "/artifacts/final.state"); asset(dir .. "/artifacts/final.state")
    shot(dir .. "/artifacts/final.png")
    same_frame(before, "final snapshot")
    result.final_frame = before
    result.status, result.execution = "done", "pass"
    result.reason = result.completion == "inconclusive" and "execution finished; no completion checks" or
                    (verdict == "pass" and "execution and completion checks passed" or "execution finished; completion checks failed")
    finished = true
end
local function tick()
    if not initialized then initialize() end
    if not started and not identity_gate then start_session() end
    after_advance()
    heartbeat(identity_gate and "identity" or (gate and "admission" or "running"))
    if identity_gate then
        if not identity_poll() then return "yield" end
        return "continue"
    end
    if gate and not gate_poll() then return "yield" end
    if index > #program.steps then finalize(); return "exit" end
    if not current then
        current = program.steps[index]
        event("step_started")
        current._left, current._segment, current._elapsed = current.frames, 1, 0
        if current.op == "input" then
            current._inputs = {}
            for i, segment in ipairs(current.segments) do
                integer(segment.frames, "segment frames", 1)
                current._inputs[i] = buttons(segment.players)
            end
        elseif current.op == "advance" then
            integer(current.frames, "advance frames", 0)
            current._buttons = buttons({})
        elseif current.op == "replay" then
            integer(current.frames, "replay frames", 0)
            if not movie_owned or movie.mode() ~= "PLAY" then error("replay requires initial active movie") end
        elseif current.op == "until" then
            integer(current.max_frames, "max_frames", 0)
            if #current.checks == 0 then error("until requires nonempty checks") end
            current._buttons = buttons(current.players)
        end
    end
    local s, op = current, current.op
    if op == "advance" or op == "replay" then
        if op == "advance" then inactive(op) end
        if op == "replay" and (not movie_owned or
                (movie.mode() ~= "PLAY" and not (s._left == 0 and consumed == result.movie.expected_inputs))) then
            error("replay requires initial active movie")
        end
        if s._left == 0 then finish_step({consumed_inputs=consumed}); return "continue" end
        return request_advance(s._buttons, op == "replay")
    elseif op == "input" then
        inactive(op)
        while s._segment <= #s.segments do
            if s._left == nil then s._left = s.segments[s._segment].frames end
            if s._left > 0 then return request_advance(s._inputs[s._segment], false) end
            s._segment, s._left = s._segment + 1, nil
        end
        finish_step()
    elseif op == "until" then
        inactive(op)
        local values, all = sample(s.checks, true)
        event("until_check", {checks=values, elapsed=s._elapsed})
        if all then finish_step({elapsed=s._elapsed})
        elseif s._elapsed >= s.max_frames then error("until exhausted max_frames without satisfying checks")
        else return request_advance(s._buttons, false) end
    elseif op == "takeover" then
        stop_movie(); finish_step()
    elseif op == "checkpoint" then
        if type(s.name) ~= "string" or checkpoints[s.name] then error("invalid/duplicate checkpoint name") end
        local before = frame()
        local prefix = dir .. string.format("/artifacts/checkpoint_%04d", index)
        save(prefix .. ".state"); asset(prefix .. ".state")
        shot(prefix .. ".png")
        local cp = {state=prefix .. ".state", screenshot=prefix .. ".png", frame=before}
        if s.ram ~= false then
            cp.ram = dump_ram(prefix .. ".ram", s.ram_domain, s.ram_addr, s.ram_bytes)
        end
        if s.memory_dumps then
            cp.memory_dumps = {}
            for _, dump in ipairs(s.memory_dumps) do
                local path = prefix .. ".memory_" .. dump.name
                cp.memory_dumps[dump.name] = dump_ram(path, dump.domain, dump.addr, dump.bytes)
            end
        end
        if s.registers then cp.cpu_registers = cpu_registers() end
        same_frame(before, "checkpoint state/screenshot/RAM/registers")
        checkpoints[s.name] = cp
        finish_step({name=s.name, checkpoint=cp})
    elseif op == "load" then
        local cp = checkpoints[s.name]
        if not cp then error("unknown checkpoint: " .. tostring(s.name)) end
        stop_movie(); state_gate(cp.state, "load")
    elseif op == "seed_ram" then
        finish_step({seed_ram=seed_ram(s.path, s.domain, s.addr, s.bytes)})
    elseif op == "patch" then
        patch(s.writes); finish_step()
    elseif op == "observe" then
        local values = sample(s.watches, false)
        finish_step({watches=values})
    elseif op == "assert" then
        local values, all = sample(s.checks, true)
        event("assert_checked", {checks=values, pass=all})
        if not all then error("assertion failed") end
        finish_step()
    elseif op == "screenshot" then
        local path = dir .. string.format("/artifacts/screenshot_%04d.png", index)
        shot(path); finish_step({name=s.name, path=path})
    else error("unknown op: " .. tostring(op)) end
    return "continue"
end
local function failure(err)
    result.status, result.execution, result.reason = "failed", "fail", tostring(err)
    if eventfile then event("runtime_failed", {reason=tostring(err)}) end
    -- An admission failure must not export the rejected state as a reusable final.
    if started and not gate then
        local ok, why = pcall(function()
            stop_movie()
            save(dir .. "/artifacts/final.state"); asset(dir .. "/artifacts/final.state")
            shot(dir .. "/artifacts/final.png")
        end)
        if not ok then result.reason = result.reason .. "; failure snapshot: " .. tostring(why) end
    end
    finished = true
end
local function flush_result()
    result.frames_advanced, result.movie.consumed_inputs = advances, consumed
    result.final_frame = frame()
    publish(dir .. "/runtime_result.json", result)
    if eventfile then assert(eventfile:close()); eventfile = nil end
    heartbeat("finished")
end

-- Never yield across pcall (Lua 5.1). Only this driver can advance, and only
-- after an explicit interpreter request. Admission/UI yields stay paused.
while not finished do
    local ok, action = pcall(tick)
    if not ok then
        local handled, why = pcall(failure, action)
        if not handled then
            result.status, result.execution, result.reason = "failed", "fail", tostring(action) .. "; reporting: " .. tostring(why)
            finished = true
        end
    elseif action == "advance" then
        client.unpause()
        emu.frameadvance()
        client.pause()
    elseif action == "yield" then
        client.pause()
        emu.yield()
    end
end
client.pause()
local ok, why = pcall(flush_result)
if not ok then error("cannot write runtime result: " .. tostring(why)) end
client.exit()
-- CloseEmulator schedules UI shutdown; permit it without a game-frame advance.
emu.yield()
