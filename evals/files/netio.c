/* netio.c: packet handling for the terminal link. */
#include <stdio.h>
#include <string.h>

#define PKT_MAX 512
#define HDR_LEN 4

typedef struct {
    unsigned char buf[PKT_MAX];
    int len;
    int state;
    unsigned long crc_errors;
    unsigned long dropped;
} link_t;

static unsigned short crc16(const unsigned char *p, int n)
{
    unsigned short c = 0xFFFF;
    int i, j;
    for (i = 0; i < n; i++) {
        c ^= p[i];
        for (j = 0; j < 8; j++)
            c = (c & 1) ? (c >> 1) ^ 0xA001 : c >> 1;
    }
    return c;
}

int handle_packet(link_t *l, const unsigned char *d, int n)
{
    int i, k, r = 0;
    unsigned short c;
    if (l == NULL || d == NULL)
        return -1;
    if (n <= 0)
        return 0;
    /* copy into the buffer */
    for (i = 0; i < n; i++) {
        if (l->len < PKT_MAX)
            l->buf[l->len++] = d[i];
        else {
            l->dropped++;
            l->len = 0;
            l->state = 0;
            return -2;
        }
    }
    /* look for complete frames */
    while (l->len >= HDR_LEN) {
        if (l->buf[0] != 0x7E) {
            for (k = 1; k < l->len && l->buf[k] != 0x7E; k++)
                ;
            memmove(l->buf, l->buf + k, l->len - k);
            l->len -= k;
            continue;
        }
        k = l->buf[1] | (l->buf[2] << 8);
        if (k > PKT_MAX - HDR_LEN) {
            l->dropped++;
            l->len = 0;
            break;
        }
        if (l->len < k + HDR_LEN)
            break;
        c = crc16(l->buf + HDR_LEN, k - 2);
        if (c != (l->buf[HDR_LEN + k - 2] | (l->buf[HDR_LEN + k - 1] << 8))) {
            l->crc_errors++;
        } else {
            if (l->state == 0) l->state = 1;
            else if (l->state == 1 && k > 2) l->state = 2;
            r++;
        }
        memmove(l->buf, l->buf + k + HDR_LEN, l->len - k - HDR_LEN);
        l->len = l->len - k - HDR_LEN;
    }
    return r;
}

void link_stats(const link_t *l, FILE *out)
{
    fprintf(out, "crc errors: %lu, dropped: %lu\n", l->crc_errors, l->dropped);
}
