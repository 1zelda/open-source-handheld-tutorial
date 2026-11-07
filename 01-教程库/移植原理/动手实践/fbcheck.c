/* fbcheck.c -- 掌机移植最小样板：探屏幕 + 探手柄 + 可选涂一屏
 * 不吃任何第三方库，只吃 Linux 内核 ABI，所以能静态编译塞进任何固件。
 */

#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

static int fb_probe(const char *dev) {
  struct fb_fix_screeninfo finfo;
  struct fb_var_screeninfo vinfo;
  int fd = open(dev, O_RDWR);
  if (fd < 0) {
    printf("  %-10s open 失败: %s\n", dev, strerror(errno));
    return -1;
  }
  if (ioctl(fd, FBIOGET_VSCREENINFO, &vinfo) < 0) {
    printf("  %-10s 取分辨率失败: %s\n", dev, strerror(errno));
    close(fd);
    return -1;
  }
  if (ioctl(fd, FBIOGET_FSCREENINFO, &finfo) < 0) {
    printf("  %-10s 取显存信息失败: %s\n", dev, strerror(errno));
    close(fd);
    return -1;
  }
  printf("  %s: %dx%d  虚拟%d x 物理%d  bpp=%u  一行%u字节  显存%lu B\n", dev,
         vinfo.xres, vinfo.yres, vinfo.xres_virtual, vinfo.yres_virtual,
         vinfo.bits_per_pixel, finfo.line_length,
         (unsigned long)finfo.smem_len);
  close(fd);
  return 0;
}

static void input_probe(void) {
  int found = 0;
  for (int i = 0; i < 8; ++i) {
    char path[64];
    snprintf(path, sizeof(path), "/dev/input/event%d", i);
    int fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd < 0)
      continue;
    found++;
    char name[80] = {0};
    if (ioctl(fd, EVIOCGNAME(sizeof(name)), name) < 0)
      snprintf(name, sizeof(name), "(读不到名字)");
    unsigned long bits[KEY_MAX / (8 * sizeof(long)) + 1];
    memset(bits, 0, sizeof(bits));
    int has_up = 0;
    if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(bits)), bits) >= 0)
      has_up = (bits[KEY_UP / (8 * sizeof(long))] >> (KEY_UP % (8 * sizeof(long)))) & 1;
    printf("  event%d: 设备名「%s」有方向键=%s\n", i, name,
           has_up ? "是" : "否");
    close(fd);
  }
  if (!found)
    printf("  /dev/input/event0..7 一个都打不开\n");
}

static int paint(unsigned color) {
  int fd = open("/dev/fb0", O_RDWR);
  if (fd < 0) {
    printf("  打不开 /dev/fb0: %s\n", strerror(errno));
    return 1;
  }
  struct fb_var_screeninfo vinfo;
  if (ioctl(fd, FBIOGET_VSCREENINFO, &vinfo) < 0) {
    printf("  ioctl 失败: %s\n", strerror(errno));
    close(fd);
    return 1;
  }
  size_t screens = (size_t)vinfo.xres * vinfo.yres * vinfo.bits_per_pixel / 8;
  void *fb = mmap(NULL, screens, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (fb == MAP_FAILED) {
    printf("  mmap 失败: %s\n", strerror(errno));
    close(fd);
    return 1;
  }
  if (vinfo.bits_per_pixel == 16) {
    unsigned short *px = (unsigned short *)fb;
    for (size_t i = 0; i < (size_t)vinfo.xres * vinfo.yres; ++i)
      px[i] = (unsigned short)color;
  } else {
    unsigned *px = (unsigned *)fb;
    for (size_t i = 0; i < (size_t)vinfo.xres * vinfo.yres; ++i)
      px[i] = color;
  }
  printf("  已把 %dx%d@%ubpp 涂成 0x%06X\n", vinfo.xres, vinfo.yres,
         vinfo.bits_per_pixel, color);
  munmap(fb, screens);
  close(fd);
  return 0;
}

int main(int argc, char *argv[]) {
  printf("fbcheck —— 交叉编译自 Windows，跑在掌机上\n");
  printf("CPU 架构宏: ");
#if defined(__aarch64__)
  printf("aarch64(64位 ARMv8)");
#elif defined(__arm__)
  printf("arm 32位");
#elif defined(__x86_64__)
  printf("x86_64");
#else
  printf("未知");
#endif
  printf("\n");
  printf("页大小=%ld B  指针大小=%zu B\n", sysconf(_SC_PAGESIZE),
         sizeof(void *));

  printf("屏幕:\n");
  fb_probe("/dev/fb0");
  fb_probe("/dev/fb1");

  printf("输入设备:\n");
  input_probe();

  for (int i = 1; i < argc; ++i) {
    if (!strcmp(argv[i], "--green"))
      return paint(0x00FF00u);
    if (!strcmp(argv[i], "--blue"))
      return paint(0x0000FFu);
  }
  printf("提示: 加 --green 或 --blue 可以真涂一屏颜色\n");
  return 0;
}
