// How layout D reads the review: the calls of one poll, and which poll counts. DOM-free.

/** One poll's answers: {review, mode, agent, changeset, threads, viewed, reviewPath, done}.
 *  <last>: the answers shown now, or null. */
export async function readReview(api, last) {
  const get = (path) => api("GET", path);
  const review = await get("/api/review"); // first: the watcher follows the checked-out branch
  // The changeset says the view the watcher shows: threads and review path are then read in it
  const shown = get("/api/changeset").then(async (changeset) => {
    const view = encodeURIComponent(changeset.view ?? "");
    const [threads, { files: viewed }, reviewPath] = await Promise.all([
      get(`/api/threads?view=${view}`),
      get("/api/viewed"),
      // A failed call keeps the path shown, so one bad poll doesn't reorder the files. Never
      // another view's: it is cut down to that view's files
      get(`/api/review-path?view=${view}`).then((a) => a.path,
        () => (last?.review.id === review.id && last.changeset.view === changeset.view ? last.reviewPath : null)),
    ]);
    return { changeset, threads, viewed, reviewPath };
  });
  const [mode, agent, done, inView] = await Promise.all([
    get("/api/mode"),
    get("/api/agent").catch(() => null), // a wrong agent list shows no agent, not no review
    get("/api/done"),
    shown,
  ]);
  return { review, mode, agent, done, ...inView };
}

/** A refresh in which only the newest read counts: <apply> gets its answers, or <fail> its
 *  error. A read that a newer one overtook has older news, so it is dropped, and its refresh
 *  ends with the newer one's: what awaits a refresh then reads news at least as new. */
export function newestOnly(read, apply, fail) {
  let latest = 0, newest;
  async function run(mine) {
    let answers;
    try {
      answers = await read();
    } catch (e) {
      return mine === latest ? fail(e) : newest;
    }
    return mine === latest ? apply(answers) : newest;
  }
  return () => (newest = run(++latest));
}
