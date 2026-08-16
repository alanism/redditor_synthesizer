import js from '@eslint/js';
import ts from 'typescript-eslint';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';

export default ts.config(
	js.configs.recommended,
	...ts.configs.recommended,
	...svelte.configs['flat/recommended'],
	{
		languageOptions: {
			globals: {
				...globals.browser,
				...globals.node
			}
		},
		rules: {
			// redditTypes.ts mirrors Reddit's raw API shape — hundreds of fields whose
			// real types are unknown/nullable. `any` there is deliberate; don't block
			// the build over it, but keep it visible for new code.
			'@typescript-eslint/no-explicit-any': 'warn',

			// Svelte 5 runes migration rules (prefer-svelte-reactivity,
			// no-navigation-without-resolve) flag working Svelte 4-style patterns.
			// Converting is a migration task, not a lint gate. Revisit on the runes pass.
			'svelte/prefer-svelte-reactivity': 'off',
			'svelte/no-navigation-without-resolve': 'off',

			// underscore-prefixed identifiers are the codebase's convention for
			// intentionally-unused params (e.g. `as _, i` in each blocks)
			'@typescript-eslint/no-unused-vars': [
				'error',
				{
					argsIgnorePattern: '^_',
					varsIgnorePattern: '^_',
					caughtErrorsIgnorePattern: '^_'
				}
			]
		}
	},
	{
		files: ['**/*.svelte'],
		languageOptions: {
			parserOptions: {
				parser: ts.parser
			}
		}
	},
	{
		ignores: ['build/', '.svelte-kit/', 'node_modules/', 'reddit-intel/', 'package/', '.hermes/']
	}
);
