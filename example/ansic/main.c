#include <stdio.h>

/* This is
 * a multiline
 * comment*/

#define A(a) a

int main(int argc, char **argv)
{
    // this is a single line comment
	switch (A(argc)) {
	case 1:
	  break
	default:
	}

	return 0;
}
