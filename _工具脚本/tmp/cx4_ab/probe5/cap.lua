
local dir = "F:/开源掌机教程/_工具脚本/tmp/cx4_ab/probe5/frames/"
local f = io.open("F:/开源掌机教程/_工具脚本/tmp/cx4_ab/probe5/cap.txt", "w")
local hb = io.open("F:/开源掌机教程/_工具脚本/tmp/cx4_ab/probe5/heartbeat.txt", "w")
local N = 5
local status = "complete"
local captured = 0
for i = 0, N - 1 do
	client.screenshot(dir .. string.format("f%04d.png", i))
	captured = i + 1
	local mode = tostring(movie.mode())
	hb:seek("set", 0)
	hb:write(string.format("%08d %-10s\n", captured, mode))
	hb:flush()
	if i == N - 1 then
		break
	end
	emu.frameadvance()
	if movie.mode() ~= "PLAY" and movie.mode() ~= "RECORD" then
		f:write("desync at " .. i .. " mode=" .. tostring(movie.mode()) .. "\n")
		status = "desync"
		break
	end
end
f:write(string.format("status=%s n=%d mode=%s\n", status, captured, tostring(movie.mode())))
f:flush()
f:close()
hb:close()
client.exit()
