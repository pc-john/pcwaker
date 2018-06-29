%module bdaqctrl

%include <typemaps.i>
%include <python/cwstring.i>
%apply wchar_t       * {WCHAR *}
%apply wchar_t const * {WCHAR const *}
%apply const wchar_t * {const WCHAR *}
%include <cpointer.i>
%pointer_class(unsigned char, uint8);

%{
/* Includes the header in the wrapper code */
#include "build/inc/bdaqctrl.h"
%}

/* Parse the header file to generate wrappers */
%include "build/inc/bdaqctrl.h"
