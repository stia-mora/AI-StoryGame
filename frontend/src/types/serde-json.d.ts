// ts-rs exports reference a Rust workspace that is optional in this Python checkout.
// Keep its serde_json type available without requiring generated build directories.
declare module '*bindings/serde_json/JsonValue' {
  export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
}
