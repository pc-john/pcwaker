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
#include "USB-4761-amd64/inc/bdaqctrl.h"
%}

/* Parse the header file to generate wrappers */
%include "USB-4761-amd64/inc/bdaqctrl.h"
