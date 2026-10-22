
void** __get_tls_hooks(void) {
#include "platform/bionic/tls.h"
  return __get_tls();
}

