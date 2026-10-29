// Shows a helpful line inside a <select> when the lookup list is empty, so an
// empty dropdown reads as "nothing set up yet" instead of "this is broken".
export default function NoOptions({ when, label }) {
  if (!when) return null
  return (
    <option value="" disabled>
      {label}
    </option>
  )
}
