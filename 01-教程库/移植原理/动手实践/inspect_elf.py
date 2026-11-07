import os
import re

BUILD = r"F:\开源掌机教程\_scratch\port_build"
os.chdir(BUILD)

dyn = open("fbcheck_a64_gnu217", "rb").read()
mus = open("fbcheck_a64_musl_static", "rb").read()
arm = open("fbcheck_armv7_musl_static", "rb").read()

pat_so = rb"lib[a-z0-9_+.\-]*\.so[0-9.]*"
pat_ver = rb"GLIBC_[0-9.]+"
pat_ld = rb"/lib[a-zA-Z0-9/_\-]*ld-[a-zA-Z0-9._\-]+"

print("== gnu217 (动态) ==")
print("  INTERP :", sorted(set(x.decode() for x in re.findall(pat_ld, dyn))))
print("  .so 串 :", sorted(set(x.decode() for x in re.findall(pat_so, dyn))))
print("  GLIBC 版:", sorted(set(x.decode() for x in re.findall(pat_ver, dyn))))
print("== musl 静态 aarch64 ==")
print("  .so 串 :", sorted(set(x.decode() for x in re.findall(pat_so, mus))))
print("  INTERP :", sorted(set(x.decode() for x in re.findall(pat_ld, mus))))
print("  GLIBC 版:", sorted(set(x.decode() for x in re.findall(pat_ver, mus))))
print("== musl 静态 armv7 ==")
print("  .so 串 :", sorted(set(x.decode() for x in re.findall(pat_so, arm))))
print("  INTERP :", sorted(set(x.decode() for x in re.findall(pat_ld, arm))))
