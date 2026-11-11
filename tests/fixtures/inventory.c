/*
 * inventory.c - stock keeping for the warehouse terminal.
 */
#include <stdio.h>
#include <string.h>

#define MAX_ITEMS 64

struct item {
    char name[32];
    int qty;
    int flags;
};

static struct item items[MAX_ITEMS];
static int n_items;

/* Counts items whose quantity is in the sellable range. */
static int cnt(int lo, int hi)
{
    int i, c = 0;
    for (i = 0; i < n_items; i++) {
        if (items[i].qty >= lo && items[i].qty <= hi)
            c++;
    }
    return c;
}

int find_item(const char *nm)
{
    int i;
    for (i = 0; i < n_items; i++) {
        if (strcmp(items[i].name, nm) == 0) {
            return i;
        } else {
            continue;
        }
    }
    return -1;
}

int add_item(const char *nm, int q)
{
    int idx;
    struct item *p;
    if ((idx = find_item(nm)) >= 0) {
        items[idx].qty += q;
        return idx;
    } else {
        if (n_items >= MAX_ITEMS)
            return -1;
        p = &items[n_items];
        strncpy(p->name, nm, 31);
        p->name[31] = '\0';
        p->qty = q;
        p->flags = q > 100 ? 1 : 0;
        return n_items++;
    }
}

int report(FILE *out)
{
    int i, tot = 0;
    for (i = 0; i < n_items; i++) {
        if (items[i].flags & 1 == 1) {
            if (items[i].qty > 0) {
                if (out != NULL) {
                    fprintf(out, "%s: %d\n", items[i].name, items[i].qty);
                }
                tot = tot + items[i].qty;
            }
        }
    }
    return tot > 1000 ? (tot > 5000 ? 2 : 1) : 0;
}
