#ifndef HWCOMPOSER_NIGHTLIGHT_H
#define HWCOMPOSER_NIGHTLIGHT_H

#include <QObject>
#include <QMutex>
#include <QDateTime>
#include <QFileSystemWatcher>
#include <QString>

class QOpenGLContext;

// Night light as a colour transform applied while the frame is composed: the vendor composer refuses
// SET_COLOR_TRANSFORM on this device, so the plugin multiplies the finished frame by per-channel gains
// (a diagonal colour matrix) right before it is queued to the composer. The gains come from the one-line
// file $XDG_RUNTIME_DIR/hwc-nightlight ("r g b", each 0..1); a missing file or "1 1 1" costs nothing.
class NightLight : public QObject
{
    Q_OBJECT
public:
    NightLight();

    bool active() const;
    // Draw the multiply pass into the currently bound window surface. The GL context must be current.
    void apply(QOpenGLContext *context);

private slots:
    void start();
    void reload();

private:
    QString m_path;
    QFileSystemWatcher *m_watcher;
    QDateTime m_stamp;
    mutable QMutex m_mutex;
    float m_gain[3];
    unsigned int m_program;
    int m_gainLocation;
    QOpenGLContext *m_programContext;
};

#endif
