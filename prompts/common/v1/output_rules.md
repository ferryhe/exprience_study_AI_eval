Output must be valid JSON conforming to the supplied schema. Use the exact required property names and enumerated values. Do not emit additional properties, comments, Markdown fences, NaN, Infinity, executable instructions, or encoded binary data.

Use decimal strings for authoritative numeric values when the schema requests a string. Preserve null as null rather than substituting zero, an empty string, or an invented estimate. Keep identifiers stable and unique within the response.

A completed status means the requested response content is present; it does not mean local tests ran or actuarial review occurred. Put missing inputs, conflicts, known limitations, and incomplete work in their designated arrays.
