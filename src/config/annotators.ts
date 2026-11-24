import type { Annotator } from '../types'

export function humanAnnotators(annotators: Annotator[]): Annotator[] {
  return annotators.filter(annotator => annotator.type === 'human' && annotator.active !== false)
}
