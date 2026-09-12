/* h5check -- is this areaDetector HDF5 file what the IOC says it is?
 *
 *   h5check [-l] file.h5
 *
 * Prints rank/dims/type/chunk (+ the filter pipeline), pixel statistics of the first,
 * middle and last frame, NDArrayUniqueId continuity, and the frame rate from the camera
 * and host timestamps stored in the file. With -l it also lists the NDAttributes datasets
 * and which of the standard data paths exist (the file "contract" downstream code relies on).
 *
 * Exit codes: 0 ok; 1 cannot open the file or the data dataset; 2 a frame could not be
 * read (missing/unavailable filter, truncated file). Every existing output line keeps its
 * format -- tests/helpers/h5.py parses them.
 */
#include <hdf5.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int read1d_d(hid_t f, const char *p, double **out, hsize_t *n){
    if (H5Lexists(f, p, H5P_DEFAULT) <= 0) return -1;
    hid_t d = H5Dopen2(f, p, H5P_DEFAULT); if (d < 0) return -1;
    hid_t s = H5Dget_space(d);
    H5Sget_simple_extent_dims(s, n, NULL);
    *out = malloc(sizeof(double) * *n);
    H5Dread(d, H5T_NATIVE_DOUBLE, H5S_ALL, H5S_ALL, H5P_DEFAULT, *out);
    H5Sclose(s); H5Dclose(d); return 0;
}

static herr_t list_cb(hid_t g, const char *name, const H5L_info_t *info, void *op){
    (void)g; (void)info; (void)op;
    printf(" %s", name);
    return 0;
}

int main(int argc, char **argv){
    int list = 0; const char *path = NULL;
    for (int i = 1; i < argc; i++){
        if (!strcmp(argv[i], "-l")) list = 1; else path = argv[i];
    }
    if (!path) { fprintf(stderr, "usage: h5check [-l] file.h5\n"); return 1; }
    H5Eset_auto2(H5E_DEFAULT, NULL, NULL);
    int rc = 0;
    hid_t f = H5Fopen(path, H5F_ACC_RDONLY, H5P_DEFAULT);
    if (f < 0) { printf("%s: cannot open\n", path); return 1; }
    hid_t d = H5Dopen2(f, "/entry/data/data", H5P_DEFAULT);
    if (d < 0) { printf("%s: no /entry/data/data\n", path); return 1; }
    hid_t s = H5Dget_space(d), t = H5Dget_type(d);
    hsize_t dm[3] = {0,0,0}; int rank = H5Sget_simple_extent_dims(s, dm, NULL);
    size_t tsz = H5Tget_size(t); H5T_sign_t sg = H5Tget_sign(t);
    printf("%-16s rank=%d dims=[%llu x %llu x %llu] type=%s%zu", path, rank,
        (unsigned long long)dm[0], (unsigned long long)dm[1], (unsigned long long)dm[2],
        sg == H5T_SGN_NONE ? "uint" : "int", tsz*8);
    /* chunking and filter pipeline */
    hid_t pl = H5Dget_create_plist(d); hsize_t cd[3]={0,0,0};
    if (H5Pget_layout(pl) == H5D_CHUNKED) { H5Pget_chunk(pl, 3, cd); printf(" chunk=[%llu x %llu x %llu]", (unsigned long long)cd[0],(unsigned long long)cd[1],(unsigned long long)cd[2]); }
    int nf = H5Pget_nfilters(pl);
    printf(" filters=[");
    for (int i = 0; i < nf; i++){
        unsigned flags = 0; size_t nelm = 0; unsigned cfg = 0;
        H5Z_filter_t id = H5Pget_filter2(pl, (unsigned)i, &flags, &nelm, NULL, 0, NULL, &cfg);
        printf("%s%d", i ? "," : "", (int)id);
    }
    printf("]\n");
    for (int i = 0; i < nf; i++){
        unsigned flags = 0; size_t nelm = 0; unsigned cfg = 0;
        H5Z_filter_t id = H5Pget_filter2(pl, (unsigned)i, &flags, &nelm, NULL, 0, NULL, &cfg);
        printf("  filter %d: %s\n", (int)id, H5Zfilter_avail(id) > 0 ? "available" : "UNAVAILABLE");
    }
    /* sample frames: first, middle, last */
    hsize_t fsz = dm[1]*dm[2]; unsigned short *buf = malloc(fsz*2 + 2);
    hsize_t idx[3] = {0, dm[0]/2, dm[0] ? dm[0]-1 : 0}; const char *nm[3] = {"first","middle","last"};
    for (int k = 0; k < 3 && dm[0] > 0; k++){
        hsize_t start[3] = {idx[k],0,0}, cnt[3] = {1,dm[1],dm[2]};
        hid_t ms = H5Screate_simple(3, cnt, NULL);
        H5Sselect_hyperslab(s, H5S_SELECT_SET, start, NULL, cnt, NULL);
        if (H5Dread(d, H5T_NATIVE_USHORT, ms, s, H5P_DEFAULT, buf) < 0) { printf("  frame %llu: READ FAILED\n",(unsigned long long)idx[k]); rc = 2; H5Sclose(ms); continue; }
        unsigned mn = 65535, mx = 0; double sum = 0; hsize_t zeros = 0;
        for (hsize_t i = 0; i < fsz; i++){ unsigned v = buf[i]; if (v<mn) mn=v; if (v>mx) mx=v; sum+=v; if(!v) zeros++; }
        printf("  %-6s frame %5llu: min=%u max=%u mean=%.1f zeros=%.2f%%\n", nm[k], (unsigned long long)idx[k], mn, mx, sum/fsz, 100.0*zeros/fsz);
        H5Sclose(ms);
    }
    /* attributes datasets */
    double *uid=NULL, *ts=NULL, *sec=NULL, *nsec=NULL; hsize_t nu=0, nt=0, ns=0, nn=0;
    if (read1d_d(f, "/entry/instrument/NDAttributes/NDArrayUniqueId", &uid, &nu) == 0 && nu > 0){
        long gaps = 0, dups = 0; for (hsize_t i = 1; i < nu; i++){ double dlt = uid[i]-uid[i-1]; if (dlt > 1) gaps += (long)dlt-1; else if (dlt < 1) dups++; }
        printf("  UniqueId: n=%llu first=%.0f last=%.0f span=%.0f missing=%ld nonmonotonic=%ld\n", (unsigned long long)nu, uid[0], uid[nu-1], uid[nu-1]-uid[0]+1, gaps, dups);
    } else printf("  UniqueId: dataset absent\n");
    if (read1d_d(f, "/entry/instrument/NDAttributes/NDArrayTimeStamp", &ts, &nt) == 0 && nt > 1){
        double span = ts[nt-1]-ts[0], mind = 1e9, maxd = 0;
        for (hsize_t i = 1; i < nt; i++){ double dd = ts[i]-ts[i-1]; if (dd<mind) mind=dd; if (dd>maxd) maxd=dd; }
        printf("  TimeStamp (camera): span=%.3f s -> %.1f fps over %llu frames; frame interval min=%.2f ms max=%.2f ms\n", span, (nt-1)/span, (unsigned long long)nt, mind*1e3, maxd*1e3);
    } else printf("  TimeStamp: dataset absent\n");
    if (read1d_d(f, "/entry/instrument/NDAttributes/NDArrayEpicsTSSec", &sec, &ns) == 0 && read1d_d(f, "/entry/instrument/NDAttributes/NDArrayEpicsTSnSec", &nsec, &nn) == 0 && ns > 1){
        double t0 = sec[0]+nsec[0]*1e-9, t1 = sec[ns-1]+nsec[ns-1]*1e-9;
        printf("  EpicsTS (host):     span=%.3f s -> %.1f fps\n", t1-t0, (ns-1)/(t1-t0));
    }
    if (list){
        printf("  NDAttributes:");
        if (H5Lexists(f, "/entry/instrument/NDAttributes", H5P_DEFAULT) > 0){
            hid_t g = H5Gopen2(f, "/entry/instrument/NDAttributes", H5P_DEFAULT);
            if (g >= 0){ hsize_t i = 0; H5Literate(g, H5_INDEX_NAME, H5_ITER_NATIVE, &i, list_cb, NULL); H5Gclose(g); }
        }
        printf("\n  datasets:");
        const char *cands[] = {"/entry/data/data", "/entry/instrument/detector/data",
                               "/entry/instrument/performance/timestamp", "/entry/instrument/NDAttributes", NULL};
        for (int i = 0; cands[i]; i++) if (H5Lexists(f, cands[i], H5P_DEFAULT) > 0) printf(" %s", cands[i]);
        printf("\n");
    }
    return rc;
}
