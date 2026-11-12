# TiniActor / TinyTwinGenerator

The supplied `TiniActor-main` implementation informed the XML-to-LTS pipeline,
observable-message selectors, iterative internal-SCC algorithm, weak-equivalence
approach, and optional mCRL2 integration. In particular, see the supplied
`cast_and_extract.py`, `lts_reduction.py`, `time_accumulator.py`, and
`tinytwin.py`. `semanticchecker/lts.py` adapts the iterative SCC approach.

The Afra `.statespace` examples and observable file in `examples/` are copied
unchanged from the supplied `TiniActor-main/samples/1` artifact. SemanticChecker
uses unit-time normalization and compares two rooted systems directly.

The original project carries this license:

MIT License

Copyright (c) 2026 AliAtaollahi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
