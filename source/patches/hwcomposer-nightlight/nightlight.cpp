#include "nightlight.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QMetaObject>
#include <QOpenGLContext>
#include <QOpenGLFunctions>
#include <QWindow>

static const char *vertexSource =
    "attribute vec2 p;\n"
    "void main() { gl_Position = vec4(p, 0.0, 1.0); }\n";
static const char *fragmentSource =
    "precision mediump float;\n"
    "uniform vec3 gain;\n"
    "void main() { gl_FragColor = vec4(gain, 1.0); }\n";

NightLight::NightLight()
    : m_watcher(0), m_program(0), m_gainLocation(-1), m_programContext(0)
{
    m_gain[0] = m_gain[1] = m_gain[2] = 1.0f;
    QByteArray dir = qgetenv("XDG_RUNTIME_DIR");
    if (!dir.isEmpty())
        m_path = QString::fromLocal8Bit(dir) + QLatin1String("/hwc-nightlight");
    // The event dispatcher does not exist yet while the platform integration is constructed.
    QMetaObject::invokeMethod(this, "start", Qt::QueuedConnection);
}

void NightLight::start()
{
    if (m_path.isEmpty())
        return;
    m_watcher = new QFileSystemWatcher(this);
    m_watcher->addPath(QFileInfo(m_path).absolutePath());
    connect(m_watcher, SIGNAL(directoryChanged(QString)), this, SLOT(reload()));
    connect(m_watcher, SIGNAL(fileChanged(QString)), this, SLOT(reload()));
    reload();
}

void NightLight::reload()
{
    QFileInfo info(m_path);
    if (m_watcher && info.exists() && !m_watcher->files().contains(m_path))
        m_watcher->addPath(m_path);

    QDateTime stamp = info.exists() ? info.lastModified() : QDateTime();
    if (stamp == m_stamp && info.exists())
        return;
    m_stamp = stamp;

    float gain[3] = { 1.0f, 1.0f, 1.0f };
    QFile file(m_path);
    if (file.open(QIODevice::ReadOnly)) {
        const QList<QByteArray> parts = file.readLine(128).simplified().split(' ');
        if (parts.size() >= 3) {
            for (int i = 0; i < 3; ++i) {
                bool ok = false;
                float v = parts.at(i).toFloat(&ok);
                gain[i] = ok ? qBound(0.0f, v, 1.0f) : 1.0f;
            }
        }
    }

    {
        QMutexLocker lock(&m_mutex);
        if (gain[0] == m_gain[0] && gain[1] == m_gain[1] && gain[2] == m_gain[2])
            return;
        for (int i = 0; i < 3; ++i)
            m_gain[i] = gain[i];
    }

    // A static screen is not redrawn by itself.
    const QWindowList windows = QGuiApplication::allWindows();
    for (QWindow *w : windows)
        QMetaObject::invokeMethod(w, "update", Qt::QueuedConnection);
}

bool NightLight::active() const
{
    QMutexLocker lock(&m_mutex);
    return m_gain[0] < 1.0f || m_gain[1] < 1.0f || m_gain[2] < 1.0f;
}

void NightLight::apply(QOpenGLContext *context)
{
    if (!context)
        return;
    float gain[3];
    {
        QMutexLocker lock(&m_mutex);
        for (int i = 0; i < 3; ++i)
            gain[i] = m_gain[i];
    }

    QOpenGLFunctions *f = context->functions();

    if (!m_program || m_programContext != context) {
        GLuint vs = f->glCreateShader(GL_VERTEX_SHADER);
        f->glShaderSource(vs, 1, &vertexSource, 0);
        f->glCompileShader(vs);
        GLuint fs = f->glCreateShader(GL_FRAGMENT_SHADER);
        f->glShaderSource(fs, 1, &fragmentSource, 0);
        f->glCompileShader(fs);
        GLuint prog = f->glCreateProgram();
        f->glAttachShader(prog, vs);
        f->glAttachShader(prog, fs);
        f->glBindAttribLocation(prog, 0, "p");
        f->glLinkProgram(prog);
        f->glDeleteShader(vs);
        f->glDeleteShader(fs);
        GLint linked = 0;
        f->glGetProgramiv(prog, GL_LINK_STATUS, &linked);
        if (!linked) {
            qWarning("hwcomposer night light: shader link failed, night light disabled");
            f->glDeleteProgram(prog);
            QMutexLocker lock(&m_mutex);
            m_gain[0] = m_gain[1] = m_gain[2] = 1.0f;
            return;
        }
        m_program = prog;
        m_programContext = context;
        m_gainLocation = f->glGetUniformLocation(prog, "gain");
    }

    // Save the state touched here; Qt Quick re-establishes its own at the start of the next frame, but stay polite.
    GLint prevProgram = 0, prevArrayBuffer = 0, prevFbo = 0, prevViewport[4];
    GLint prevAttribEnabled = 0;
    GLboolean prevBlend = f->glIsEnabled(GL_BLEND), prevScissor = f->glIsEnabled(GL_SCISSOR_TEST);
    GLboolean prevDepth = f->glIsEnabled(GL_DEPTH_TEST), prevStencil = f->glIsEnabled(GL_STENCIL_TEST);
    GLboolean prevCull = f->glIsEnabled(GL_CULL_FACE), prevMask[4];
    GLint prevSrcRgb, prevDstRgb, prevSrcA, prevDstA;
    f->glGetIntegerv(GL_CURRENT_PROGRAM, &prevProgram);
    f->glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &prevArrayBuffer);
    f->glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prevFbo);
    f->glGetIntegerv(GL_VIEWPORT, prevViewport);
    f->glGetBooleanv(GL_COLOR_WRITEMASK, prevMask);
    f->glGetVertexAttribiv(0, GL_VERTEX_ATTRIB_ARRAY_ENABLED, &prevAttribEnabled);
    f->glGetIntegerv(GL_BLEND_SRC_RGB, &prevSrcRgb);
    f->glGetIntegerv(GL_BLEND_DST_RGB, &prevDstRgb);
    f->glGetIntegerv(GL_BLEND_SRC_ALPHA, &prevSrcA);
    f->glGetIntegerv(GL_BLEND_DST_ALPHA, &prevDstA);

    static const GLfloat quad[8] = { -1, -1, 1, -1, -1, 1, 1, 1 };
    const QSize size = context->surface() ? context->surface()->size() : QSize();

    f->glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (size.isValid())
        f->glViewport(0, 0, size.width(), size.height());
    f->glDisable(GL_SCISSOR_TEST);
    f->glDisable(GL_DEPTH_TEST);
    f->glDisable(GL_STENCIL_TEST);
    f->glDisable(GL_CULL_FACE);
    f->glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    f->glEnable(GL_BLEND);
    // destination colour times the gains; alpha untouched
    f->glBlendFuncSeparate(GL_DST_COLOR, GL_ZERO, GL_ZERO, GL_ONE);
    f->glUseProgram(m_program);
    f->glUniform3f(m_gainLocation, gain[0], gain[1], gain[2]);
    f->glBindBuffer(GL_ARRAY_BUFFER, 0);
    f->glEnableVertexAttribArray(0);
    f->glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, quad);
    f->glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    if (!prevAttribEnabled)
        f->glDisableVertexAttribArray(0);
    f->glBindBuffer(GL_ARRAY_BUFFER, prevArrayBuffer);
    f->glUseProgram(prevProgram);
    f->glBlendFuncSeparate(prevSrcRgb, prevDstRgb, prevSrcA, prevDstA);
    f->glColorMask(prevMask[0], prevMask[1], prevMask[2], prevMask[3]);
    if (!prevBlend) f->glDisable(GL_BLEND);
    if (prevScissor) f->glEnable(GL_SCISSOR_TEST);
    if (prevDepth) f->glEnable(GL_DEPTH_TEST);
    if (prevStencil) f->glEnable(GL_STENCIL_TEST);
    if (prevCull) f->glEnable(GL_CULL_FACE);
    f->glViewport(prevViewport[0], prevViewport[1], prevViewport[2], prevViewport[3]);
    f->glBindFramebuffer(GL_FRAMEBUFFER, prevFbo);
}
