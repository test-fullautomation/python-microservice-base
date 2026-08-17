// Minimal WASM stub — this target exists only so Qt Creator's code model
// can resolve headers for the backend source files (shown in project tree).
// The actual service is a desktop-only backend; the .ui file is a static
// asset loaded by the Widget Shell at runtime.
#include <QCoreApplication>
int main(int argc, char *argv[]) {
    QCoreApplication app(argc, argv);
    return 0;
}
