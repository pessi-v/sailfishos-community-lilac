/* lilac-no-bgra-readback: hide GL_EXT_read_format_bgra from GL_EXTENSIONS.
 *
 * The Adreno 540 driver advertises GL_EXT_read_format_bgra but rejects
 * glReadPixels(..., GL_BGRA_EXT, ...) with GL_INVALID_OPERATION and leaves the
 * buffer untouched. Qt 5.6's qt_gl_read_framebuffer_rgba8() trusts the extension
 * (its BGRA blacklist only covers some PowerVR/Mali GPUs), so every
 * QQuickWindow::grabWindow() -- lipstick's screenshots -- comes back empty.
 * With the extension hidden, Qt uses its GL_RGBA path, which works.
 * Preloaded into lipstick only.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
#include <GLES2/gl2.h>

static const char hidden[] = "GL_EXT_read_format_bgra";

const GLubyte *glGetString(GLenum name)
{
    static const GLubyte *(*real)(GLenum);
    static char *filtered;
    if (!real)
        real = (const GLubyte *(*)(GLenum))dlsym(RTLD_NEXT, "glGetString");
    const GLubyte *s = real ? real(name) : NULL;
    if (name != GL_EXTENSIONS || !s)
        return s;
    if (!filtered) {
        size_t len = strlen((const char *)s);
        char *out = malloc(len + 1);
        if (!out)
            return s;
        char *o = out;
        const char *p = (const char *)s;
        while (*p) {
            const char *end = strchr(p, ' ');
            size_t n = end ? (size_t)(end - p) : strlen(p);
            if (n && !(n == sizeof(hidden) - 1 && !strncmp(p, hidden, n))) {
                if (o != out)
                    *o++ = ' ';
                memcpy(o, p, n);
                o += n;
            }
            p += n;
            while (*p == ' ')
                p++;
        }
        *o = '\0';
        filtered = out;
    }
    return (const GLubyte *)filtered;
}
