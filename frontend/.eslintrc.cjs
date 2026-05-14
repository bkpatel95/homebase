/* ESLint config for the Vite + React frontend.
 *
 * Run with: npm run lint
 * Auto-fix with: npm run lint:fix
 */
module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:react/jsx-runtime',
    'plugin:react-hooks/recommended',
  ],
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  settings: {
    react: { version: 'detect' },
  },
  plugins: ['react-refresh'],
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    'react/prop-types': 'off',
    // The JSX runtime makes `import React` unnecessary, but our existing
    // components still do it. Don't warn on those.
    'no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^(_|React$)' },
    ],
    // Apostrophes in copy are fine.
    'react/no-unescaped-entities': 'off',
    // `while (true)` loops with an internal break are an intentional pattern
    // in our streaming code.
    'no-constant-condition': ['error', { checkLoops: false }],
    // Function declarations are scoped sanely under "use strict" + modules.
    'no-inner-declarations': 'off',
    'no-empty': ['error', { allowEmptyCatch: true }],
  },
  ignorePatterns: ['dist', 'node_modules', 'public/sw.js', '*.config.js', '.eslintrc.cjs'],
};
