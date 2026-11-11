/* legacy.c: driver for the old serial scale.
 * Комментарии в кодировке cp1251.
 */
#include <stdio.h>
#include <stdlib.h>

#define CHECK(x) if (!(x)) { rc = -1; goto out; }
#define SQR(v) ((v) * (v))

typedef int BOOL;
#define TRUE 1
#define FALSE 0

static int g_mode;

/* Старая функция в стиле K&R. */
static int clamp(v, lo, hi)
int v; int lo; int hi;
{
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

int read_weight(char *buf, int len)
{
    int rc = 0;
    int w;
    char *p;
    CHECK(buf != NULL);
    p = buf;
    w = 0;
    while (*p && p - buf < len) {
        if (*p >= '0' && *p <= '9')
            w = w * 10 + (*p - '0');
        p++;
    }
#ifdef SCALE_DEBUG
    printf("raw weight %d\n", w);
#endif
    if (g_mode == 2) {
        w = clamp(w, 0, 30000);
    }
    rc = w;
out:
    return rc;
}

BOOL is_stable(int a, int b)
{
    int d = a - b;
    if (SQR(d) < 4 && a != 0)
        return TRUE;
    else
        return FALSE;
}
