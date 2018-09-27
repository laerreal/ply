#include <stdio.h>

/* This is
 * a multiline
 * comment*/

#define A(a) a

int main(int argc, char **argv)
{
	int a[10] = {0, 1};
    /* this is another single line comment with " */
	switch (A(argc)) {
	case 1:
	  break;
	default:
	  break;
	}

	return 0;
}
