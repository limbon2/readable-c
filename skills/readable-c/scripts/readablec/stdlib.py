"""Names that the C standard headers (and a few POSIX ones) declare.

The unresolved-name check uses them: a new identifier counts as known when a
header the file includes declares it.
"""

from __future__ import annotations

_HEADERS = {
    "assert.h": "assert NDEBUG static_assert",
    "ctype.h": (
        "isalnum isalpha isblank iscntrl isdigit isgraph islower isprint ispunct isspace "
        "isupper isxdigit tolower toupper"
    ),
    "errno.h": "errno EDOM EILSEQ ERANGE EAGAIN EACCES EBADF EBUSY EEXIST EINTR EINVAL EIO "
    "ENOENT ENOMEM ENOSPC ENOTDIR EPERM EPIPE ETIMEDOUT EWOULDBLOCK",
    "float.h": (
        "FLT_RADIX FLT_MANT_DIG DBL_MANT_DIG LDBL_MANT_DIG FLT_DIG DBL_DIG LDBL_DIG FLT_MIN_EXP "
        "DBL_MIN_EXP FLT_MAX_EXP DBL_MAX_EXP FLT_MAX DBL_MAX LDBL_MAX FLT_EPSILON DBL_EPSILON "
        "LDBL_EPSILON FLT_MIN DBL_MIN LDBL_MIN"
    ),
    "inttypes.h": (
        "imaxdiv_t imaxabs imaxdiv strtoimax strtoumax PRId8 PRId16 PRId32 PRId64 PRIi32 PRIi64 "
        "PRIu8 PRIu16 PRIu32 PRIu64 PRIx8 PRIx16 PRIx32 PRIx64 PRIX32 PRIX64 PRIdPTR PRIuPTR "
        "PRIxPTR SCNd32 SCNd64 SCNu32 SCNu64 SCNx32"
    ),
    "iso646.h": "and and_eq bitand bitor compl not not_eq or or_eq xor xor_eq",
    "limits.h": (
        "CHAR_BIT SCHAR_MIN SCHAR_MAX UCHAR_MAX CHAR_MIN CHAR_MAX MB_LEN_MAX SHRT_MIN SHRT_MAX "
        "USHRT_MAX INT_MIN INT_MAX UINT_MAX LONG_MIN LONG_MAX ULONG_MAX LLONG_MIN LLONG_MAX "
        "ULLONG_MAX PATH_MAX"
    ),
    "locale.h": "lconv setlocale localeconv LC_ALL LC_COLLATE LC_CTYPE LC_MONETARY LC_NUMERIC LC_TIME",
    "math.h": (
        "acos asin atan atan2 cos sin tan cosh sinh tanh exp frexp ldexp log log10 modf pow sqrt "
        "ceil fabs floor fmod acosf asinf atanf atan2f cosf sinf tanf expf logf log10f powf "
        "sqrtf ceilf fabsf floorf fmodf round roundf lround trunc truncf fmin fmax fminf fmaxf "
        "hypot cbrt exp2 log2 log1p expm1 isnan isinf isfinite signbit copysign nan HUGE_VAL "
        "HUGE_VALF INFINITY NAN M_PI M_E"
    ),
    "setjmp.h": "jmp_buf setjmp longjmp",
    "signal.h": "sig_atomic_t signal raise SIG_DFL SIG_ERR SIG_IGN SIGABRT SIGFPE SIGILL SIGINT SIGSEGV SIGTERM",
    "stdarg.h": "va_list va_start va_arg va_end va_copy",
    "stdbool.h": "bool true false __bool_true_false_are_defined",
    "stddef.h": "ptrdiff_t size_t wchar_t NULL offsetof max_align_t",
    "stdint.h": (
        "int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t int_least8_t "
        "int_least16_t int_least32_t int_least64_t uint_least8_t uint_least16_t uint_least32_t "
        "uint_least64_t int_fast8_t int_fast16_t int_fast32_t int_fast64_t uint_fast8_t "
        "uint_fast16_t uint_fast32_t uint_fast64_t intptr_t uintptr_t intmax_t uintmax_t "
        "INT8_MIN INT16_MIN INT32_MIN INT64_MIN INT8_MAX INT16_MAX INT32_MAX INT64_MAX UINT8_MAX "
        "UINT16_MAX UINT32_MAX UINT64_MAX INTPTR_MIN INTPTR_MAX UINTPTR_MAX INTMAX_MIN INTMAX_MAX "
        "UINTMAX_MAX SIZE_MAX PTRDIFF_MIN PTRDIFF_MAX INT8_C INT16_C INT32_C INT64_C UINT8_C "
        "UINT16_C UINT32_C UINT64_C INTMAX_C UINTMAX_C"
    ),
    "stdio.h": (
        "FILE fpos_t size_t NULL EOF BUFSIZ FILENAME_MAX FOPEN_MAX L_tmpnam SEEK_CUR SEEK_END "
        "SEEK_SET TMP_MAX _IOFBF _IOLBF _IONBF stdin stdout stderr remove rename tmpfile tmpnam "
        "fclose fflush fopen freopen setbuf setvbuf fprintf fscanf printf scanf snprintf sprintf "
        "sscanf vfprintf vfscanf vprintf vscanf vsnprintf vsprintf vsscanf fgetc fgets fputc "
        "fputs getc getchar gets putc putchar puts ungetc fread fwrite fgetpos fseek fsetpos "
        "ftell rewind clearerr feof ferror perror fileno popen pclose getline fdopen"
    ),
    "stdlib.h": (
        "size_t wchar_t div_t ldiv_t lldiv_t NULL EXIT_FAILURE EXIT_SUCCESS RAND_MAX MB_CUR_MAX "
        "atof atoi atol atoll strtod strtof strtold strtol strtoll strtoul strtoull rand srand "
        "calloc free malloc realloc abort atexit exit _Exit getenv system bsearch qsort abs "
        "labs llabs div ldiv lldiv mblen mbtowc wctomb mbstowcs wcstombs aligned_alloc "
        "quick_exit at_quick_exit realpath mkstemp setenv unsetenv"
    ),
    "string.h": (
        "size_t NULL memcpy memmove strcpy strncpy strcat strncat memcmp strcmp strcoll strncmp "
        "strxfrm memchr strchr strcspn strpbrk strrchr strspn strstr strtok memset strerror "
        "strlen strdup strndup strnlen strtok_r strcasecmp strncasecmp"
    ),
    "time.h": (
        "clock_t time_t tm timespec CLOCKS_PER_SEC NULL clock difftime mktime time asctime "
        "ctime gmtime localtime strftime gmtime_r localtime_r nanosleep clock_gettime"
    ),
    "wchar.h": (
        "wchar_t wint_t mbstate_t WEOF WCHAR_MIN WCHAR_MAX wcslen wcscpy wcsncpy wcscat wcscmp "
        "wcsncmp wcschr wcsrchr wcsstr wprintf fwprintf swprintf mbrtowc wcrtomb"
    ),
    "unistd.h": (
        "read write close lseek unlink rmdir access chdir getcwd getpid getppid sleep usleep "
        "fork execv execvp pipe dup dup2 isatty ssize_t off_t pid_t STDIN_FILENO STDOUT_FILENO "
        "STDERR_FILENO F_OK R_OK W_OK X_OK"
    ),
    "fcntl.h": "open creat fcntl O_RDONLY O_WRONLY O_RDWR O_CREAT O_TRUNC O_APPEND O_EXCL O_NONBLOCK",
    "sys/types.h": "size_t ssize_t off_t pid_t uid_t gid_t mode_t dev_t ino_t time_t",
    "sys/stat.h": "stat fstat lstat mkdir chmod S_ISDIR S_ISREG S_IRUSR S_IWUSR S_IXUSR mode_t",
    "strings.h": "strcasecmp strncasecmp bzero bcopy index rindex",
}

STANDARD_HEADERS = {header: frozenset(names.split()) for header, names in _HEADERS.items()}

# Names that are always available: keywords that tree-sitter reads as identifiers,
# predefined macros and common compiler built-ins.
ALWAYS_KNOWN = frozenset(
    (  # noqa: SIM905  a word list reads best as one string
        "__FILE__ __LINE__ __DATE__ __TIME__ __func__ __FUNCTION__ __STDC__ __STDC_VERSION__ "
        "__cplusplus __attribute__ __declspec __asm__ __inline __inline__ __restrict __extension__ "
        "__builtin_expect __builtin_offsetof __builtin_va_list __builtin_unreachable __typeof__ "
        "defined sizeof _Alignof alignof _Static_assert __VA_ARGS__ main"
    ).split()
)


# C keywords, and the C99 bool spellings that tree-sitter reads as names.
C_KEYWORDS = frozenset(
    (  # noqa: SIM905  a word list reads best as one string
        "auto break case char const continue default do double else enum extern float for goto "
        "if inline int long register restrict return short signed sizeof static struct switch "
        "typedef union unsigned void volatile while _Bool _Complex _Imaginary bool true false"
    ).split()
)


def names_for(header: str) -> frozenset[str] | None:
    """The names a standard header declares, or None when the header is not in the table."""
    return STANDARD_HEADERS.get(header.replace("\\", "/"))
